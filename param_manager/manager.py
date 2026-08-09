from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, ClassVar, Dict, Optional

import requests
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from dotenv import find_dotenv, load_dotenv
from requests.exceptions import ConnectionError, Timeout
from tinydb import TinyDB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('ParamManager')

# Tipos cujo valor trafega cifrado entre a API e esta biblioteca.
SENSITIVE_TYPES = frozenset({'secret', 'user', 'users'})

# Chaves obrigatórias do envelope criptográfico. Contrato congelado com o
# servidor — ver a documentação do fast-param-manager antes de alterar.
ENVELOPE_KEYS = ('salt', 'master_key', 'crypto_data')

# Posicao de instance_name na assinatura posicional de __init__.
INSTANCE_NAME_ARG_POSITION = 6


def _is_envelope(value: Any) -> bool:
    """Diz se o valor é um envelope criptográfico íntegro."""
    return isinstance(value, dict) and all(
        key in value for key in ENVELOPE_KEYS
    )


class ParamNaoEncontradoError(Exception):
    """Levantada quando um parâmetro retorna 404 (não encontrado)."""

    pass


class ParamManager:
    _instances: ClassVar[Dict[str, 'ParamManager']] = {}
    # RLock (e não Lock) porque __new__ e __init__ adquirem o mesmo lock
    # em sequência na criação de uma instância nova.
    _lock_singleton = threading.RLock()

    def __new__(cls, *args, instance_name: str = 'default', **kwargs):
        """
        Implementa o padrão Multiton com Thread-Safety.
        """
        # instance_name é keyword-only aqui, mas o 7º posicional em
        # __init__. Sem esta derivação, uma chamada posicional registra
        # a instância no slot 'default' enquanto o __init__ a configura
        # com outro nome: dois managers lógicos, com URL, credencial e
        # arquivo local distintos, dividindo um único slot.
        if len(args) > INSTANCE_NAME_ARG_POSITION:
            instance_name = args[INSTANCE_NAME_ARG_POSITION]

        with cls._lock_singleton:
            if instance_name not in cls._instances:
                instance = super(ParamManager, cls).__new__(cls)
                cls._instances[instance_name] = instance
                # Marcar como não inicializada para o __init__
                instance._initialized = False
                logger.info(
                    f'[ParamManager: {instance_name}] Nova instância criada'
                )
            return cls._instances[instance_name]

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        api_url: str | None = None,
        cache_duration: int = 300,
        timeout: int = 5,
        local_db_path: str | None = None,
        username: str | None = None,
        password: str | None = None,
        instance_name: str = 'default',
        verify_ssl: bool | None = None,
        api_error_cooldown: int | None = None,
    ):
        # Evita re-inicialização se a instância já existe no dicionário
        if getattr(self, '_initialized', False):
            return

        # A inicialização inteira roda sob o lock: sem isso, duas threads
        # passam o guard acima ao mesmo tempo e a segunda substitui
        # self._lock enquanto a primeira o segura, zera os caches e
        # reabre o TinyDB sobre o mesmo arquivo.
        with self.__class__._lock_singleton:
            # Re-check: outra thread pode ter concluído enquanto esperávamos.
            if getattr(self, '_initialized', False):
                return

            self._instance_name = instance_name

            # Carregamento de ambiente
            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS
                dotenv_path = os.path.join(base_dir, '.env')
            else:
                base_dir = None
                dotenv_path = find_dotenv()

            load_dotenv(dotenv_path=dotenv_path)

            # 4. Prioridade de Configuração (Parâmetros de código > .env)
            # O argumento do construtor entra como fallback: sem env
            # var, a resolução é a mesma de antes. Negativo vira 0, e
            # não o fallback — ver _resolve_int_env.
            self._cache_duration = self._resolve_int_env(
                os.getenv(
                    f'{instance_name.upper()}_CACHE_DURATION',
                    os.getenv('CACHE_DURATION'),
                ),
                'CACHE_DURATION',
                cache_duration,
                negativo_vira=0,
            )
            self._username = username or os.getenv(
                f'{instance_name.upper()}_PARAMS_USERNAME',
                os.getenv('PARAMS_USERNAME'),
            )
            self._password = password or os.getenv(
                f'{instance_name.upper()}_PARAMS_PASSWORD',
                os.getenv('PARAMS_PASSWORD'),
            )

            self._lock = threading.Lock()
            # Lock dedicado ao token: reaproveitar self._lock causaria
            # reentrância com _save_to_local_db.
            self._token_lock = threading.Lock()
            self._token = None
            self._refresh_token = None
            self._token_expire_at = 0
            # Negativo aqui já é caminho quebrado (o requests estoura),
            # então cai no fallback, ao contrário de CACHE_DURATION.
            self._timeout = self._resolve_int_env(
                os.getenv('TIMEOUT'), 'TIMEOUT', timeout
            )
            # Janela do circuit breaker. Sem argumento e sem env var
            # cai em _cache_duration, que era o valor implícito antes
            # — com get_instance isso são 3600s, e um único 500
            # transitório prendia o cliente em dado local por 1 hora.
            bruto_cooldown = (
                api_error_cooldown
                if api_error_cooldown is not None
                else os.getenv(
                    f'{instance_name.upper()}_API_ERROR_COOLDOWN',
                    os.getenv('API_ERROR_COOLDOWN'),
                )
            )
            # None quando não configurado: o fallback para
            # _cache_duration é resolvido na leitura, não aqui, para
            # continuar acompanhando quem ajusta _cache_duration depois.
            self._api_error_cooldown = self._resolve_int_env(
                bruto_cooldown, 'API_ERROR_COOLDOWN', None
            )
            self._verify_ssl = self._resolve_verify_ssl(
                verify_ssl, instance_name
            )
            self._api_base_url = (
                api_url
                or os.getenv(f'API_{instance_name.upper()}_URL')
                or os.getenv('API_PARAMS_URL', '')
                or os.getenv('API_URL', '')
            )

            # 2. Isolamento do Armazenamento (TinyDB por instância)
            env_db_path = os.getenv('LOCAL_DB_PATH')
            if local_db_path:
                current_dir = local_db_path
            elif base_dir:
                current_dir = base_dir
            elif env_db_path:
                current_dir = env_db_path
            else:
                current_dir = (
                    os.path.dirname(dotenv_path)
                    if dotenv_path
                    else os.getcwd()
                )

            db_dir = os.path.join(
                current_dir, 'param_manager', self._instance_name
            )
            os.makedirs(db_dir, exist_ok=True)

            # Nome do arquivo isolado por instância
            self._db_path = os.path.join(
                db_dir, f'params_{self._instance_name}.json'
            )
            self._db = TinyDB(self._db_path)

            self._cache = {}
            self._cache_timestamp = {}
            self._param_cache = {}
            self._param_cache_timestamp = {}
            self._api_error_timestamp = {}

            self._purge_plaintext_cache()

            self._initialized = True
            logger.info(
                f'[ParamManager: {self._instance_name}] Inicializado na API:'
                f' {self._api_base_url}'
            )

    @staticmethod
    def _resolve_verify_ssl(
        verify_ssl: bool | None, instance_name: str
    ) -> bool:
        """
        Resolve a verificação TLS na precedência padrão da lib:
        construtor > {INSTANCE}_VERIFY_SSL > VERIFY_SSL.

        ESCOPO: a flag governa apenas os dois GETs de leitura
        (`_fetch_from_api` e `_fetch_param_from_api`). Autenticação e
        escrita sempre verificam a cadeia, e isso é deliberado — o
        `POST /auth/token` trafega usuário e senha, e rebaixar o TLS
        dele seria pior do que a assimetria. Sintoma prático em ambiente
        com certificado interno: a leitura funciona e a autenticação
        falha por SSL.

        O default permanece False: os ambientes que consomem esta
        biblioteca usam certificado interno, então ligar a verificação
        por padrão quebraria a leitura. Quem tem cadeia confiável pode
        (e deve) passar verify_ssl=True.
        """
        if verify_ssl is None:
            bruto = os.getenv(
                f'{instance_name.upper()}_VERIFY_SSL',
                os.getenv('VERIFY_SSL'),
            )
            if bruto is None:
                verify_ssl = False
            else:
                verify_ssl = bruto.strip().lower() in {
                    '1',
                    'true',
                    'yes',
                    'on',
                }
        return verify_ssl

    @staticmethod
    def _resolve_int_env(  # noqa: PLR0913, PLR0917
        bruto: int | str | None,
        nome: str,
        fallback: int | None,
        negativo_vira: int | None = None,
    ) -> int | None:
        """
        Resolve um inteiro de configuração sem derrubar a construção.

        Um valor malformado levantava ValueError dentro do __init__ e,
        como __new__ já registrou a instância no multiton, sobrava um
        objeto meio-construído e permanentemente inutilizável: quem
        segurava a referência passava a tomar AttributeError em vez do
        erro original. Aqui a falha vira aviso e o fallback assume.

        Zero é sempre válido. Negativo cai no fallback por padrão, para
        que um erro de digitação não vire um jeito silencioso de
        desligar o intervalo de espera.

        `negativo_vira` existe para CACHE_DURATION, onde o padrão seria
        perigoso: hoje um valor negativo faz `_is_cache_valid` devolver
        sempre False, ou seja, nunca cacheia. Mandá-lo para o fallback
        transformaria "nunca cacheia" em "cacheia por uma hora" — um
        afrouxamento silencioso numa biblioteca que serve `secret`.
        Mapeando para 0, o comportamento observável fica idêntico.
        """
        if bruto is None:
            return fallback

        valor = None
        motivo_fallback = None
        negativo = False

        # Já é int: validar sinal
        if isinstance(bruto, int):
            if bruto < 0:
                negativo = True
                motivo_fallback = f'é negativo ({bruto})'
            else:
                valor = bruto
        else:
            # String: strip e tentar int
            try:
                limpo = bruto.strip()
                if not limpo:
                    motivo_fallback = 'vazio'
                else:
                    valor = int(limpo)
                    if valor < 0:
                        negativo = True
                        motivo_fallback = f'é negativo ({valor})'
                        valor = None
            except (ValueError, AttributeError) as e:
                motivo_fallback = f'inválido ({bruto!r}): {e}'

        if motivo_fallback is not None:
            if negativo and negativo_vira is not None:
                logger.warning(
                    f'[ParamManager] {nome} {motivo_fallback}; '
                    f'usando {negativo_vira}.'
                )
                return negativo_vira
            logger.warning(
                f'[ParamManager] {nome} {motivo_fallback}; '
                f'usando fallback.'
            )
            return fallback

        return valor

    def _purge_plaintext_cache(self) -> None:
        """
        Remove do banco local valores sensíveis gravados em claro por
        versões anteriores. Opt-in: default desligado.
        """
        bruto = os.getenv(
            f'{self._instance_name.upper()}_PURGE_PLAINTEXT_CACHE',
            os.getenv('PARAM_MANAGER_PURGE_PLAINTEXT_CACHE', ''),
        )
        if bruto.strip().lower() not in {'1', 'true', 'yes', 'on'}:
            return

        try:
            for app_name in list(self._db.tables()):
                table = self._db.table(app_name)
                registro = table.get(doc_id=1)
                if not registro or not isinstance(
                    registro.get('params'), dict
                ):
                    continue
                limpos = self._discard_unencrypted(
                    app_name, registro['params']
                )
                if len(limpos) != len(registro['params']):
                    table.update({'params': limpos}, doc_ids=[1])
                    logger.warning(
                        f'[ParamManager: {self._instance_name}] Valores em '
                        f"claro removidos do cache local de '{app_name}'."
                    )
        except Exception as e:  # pragma: no cover
            logger.error(f'Falha ao purgar cache em claro: {e}')

    @staticmethod
    def get_instance(
        instance_name: str = 'default',
        api_url: str = None,
        cache_duration: int = 3600,
        timeout: int = 5,
        **kwargs,
    ) -> 'ParamManager':
        """
        Retorna ou cria a instância nomeada.
        """
        return ParamManager(
            instance_name=instance_name,
            api_url=api_url,
            cache_duration=cache_duration,
            timeout=timeout,
            **kwargs,
        )

    def _save_to_local_db(self, app_name: str, params: Dict[str, Any]) -> None:
        logger.info(
            f'[ParamManager: {self._instance_name}] '
            f'Salvando localmente: {app_name}'
        )
        with self._lock:
            table = self._db.table(app_name)
            existing = table.get(doc_id=1)
            if existing:
                # .get(): registro sem 'params' (versão antiga ou
                # escrita parcial) levantaria KeyError DENTRO do
                # lock e abortaria todo save daquele app.
                merged_params = {**(existing.get('params') or {}), **params}
                merged_params = self._discard_unencrypted(
                    app_name, merged_params
                )
                table.update(
                    {'timestamp': time.time(), 'params': merged_params},
                    doc_ids=[1],
                )
            else:
                table.insert({
                    'timestamp': time.time(),
                    'params': self._discard_unencrypted(app_name, params),
                })

    def _remove_from_local_db(self, app_name: str, param_name: str) -> None:
        """Apaga um parâmetro do banco local, sem tocar nos demais."""
        with self._lock:
            try:
                table = self._db.table(app_name)
                registro = table.get(doc_id=1)
                if not registro or not isinstance(
                    registro.get('params'), dict
                ):
                    return
                if param_name not in registro['params']:
                    return
                registro['params'].pop(param_name)
                table.update({'params': registro['params']}, doc_ids=[1])
                logger.info(
                    f'[ParamManager: {self._instance_name}] Parâmetro '
                    f"'{param_name}' removido do banco local de "
                    f"'{app_name}'."
                )
            except Exception as e:
                logger.error(
                    f'Falha ao remover {param_name} do banco local: {e}'
                )

    def _discard_unencrypted(
        self, app_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Remove parâmetros sensíveis que não estejam cifrados.

        Guarda de última linha: o banco local só pode conter o envelope.
        Vale também para o que já estava gravado, porque o filtro roda
        sobre o resultado do merge.
        """
        if not isinstance(params, dict):
            return params

        seguros = {}
        for key, param in params.items():
            if ParamManager._is_encrypted_param(param):
                seguros[key] = param
                continue
            logger.warning(
                f'[ParamManager: {self._instance_name}] Parâmetro sensível '
                f"'{key}' do app '{app_name}' não está cifrado; "
                f'descartado da persistência local.'
            )
        return seguros

    def clear_cache(
        self, app_name: Optional[str] = None, param_name: Optional[str] = None
    ) -> None:
        """
        Limpa apenas o cache desta instância.
        """
        if app_name and param_name:
            key = f'{app_name}:{param_name}'
            self._param_cache.pop(key, None)
            self._param_cache_timestamp.pop(key, None)
        elif app_name:
            self._cache.pop(app_name, None)
            self._cache_timestamp.pop(app_name, None)
            self._api_error_timestamp.pop(app_name, None)
            # Limpa chaves específicas que começam com o app
            keys_to_del = [
                k for k in self._param_cache if k.startswith(f'{app_name}:')
            ]
            for k in keys_to_del:
                self._param_cache.pop(k, None)
                self._param_cache_timestamp.pop(k, None)
        else:
            self._cache.clear()
            self._cache_timestamp.clear()
            self._param_cache.clear()
            self._param_cache_timestamp.clear()
            self._api_error_timestamp.clear()

        logger.info(f'[ParamManager: {self._instance_name}] Cache limpo.')

    def _auth_get_token(self):
        if not self._username or not self._password:
            raise ValueError(
                'Username ou password não configurados para autenticação.'
            )

        url = f'{self._api_base_url}/auth/token'

        data = {
            'username': self._username,
            'password': self._password,
        }

        res = requests.post(url, data=data, timeout=self._timeout)

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Falha ao autenticar: {res.text}')

        auth_data = res.json()
        self._token = auth_data.get('access_token')
        self._refresh_token = auth_data.get('refresh_token')

        # token TTL: 30 min
        self._token_expire_at = time.time() + 29 * 60

        return self._token

    def _auth_refresh_token(self):
        if not self._refresh_token:
            return self._auth_get_token()

        url = f'{self._api_base_url}/auth/refresh'

        data = {
            'refresh_token': self._refresh_token,
        }

        res = requests.post(url, data=data, timeout=self._timeout)

        if res.status_code != HTTPStatus.OK:
            return self._auth_get_token()

        auth_data = res.json()
        self._token = auth_data.get('access_token')
        self._refresh_token = auth_data.get('refresh_token')

        self._token_expire_at = time.time() + 29 * 60

        return self._token

    def _get_valid_token(self):
        # Double-checked locking: sem isso, N threads que percebem o token
        # expirado disparam N renovações simultâneas.
        if self._token and time.time() < self._token_expire_at:
            return self._token

        with self._token_lock:
            if self._token and time.time() < self._token_expire_at:
                return self._token
            if not self._token:
                return self._auth_get_token()
            return self._auth_refresh_token()

    def _force_token_refresh(self):
        """
        Renova o token sob o `_token_lock`, com re-check.

        Chamar `_auth_refresh_token()` direto no retry de 401 furava o
        double-checked locking de `_get_valid_token`: duas threads em
        401 simultâneo fariam `POST /auth/refresh` com o mesmo refresh
        token — de uso único no Keycloak padrão —, e a segunda
        invalidaria a sessão que a primeira acabou de renovar.
        """
        token_antes = self._token
        with self._token_lock:
            # Outra thread pode ter renovado enquanto esperávamos.
            if self._token != token_antes:
                return self._token
            return self._auth_refresh_token()

    def _auth_headers(self):
        token = self._get_valid_token()
        return {'Authorization': f'Bearer {token}'}

    def _auth_headers_opcionais(self) -> Dict[str, str]:
        """
        Header de autenticação para os caminhos de leitura.

        Hoje o servidor não exige token em GET; enquanto isso, uma
        instância sem credencial precisa continuar lendo normalmente.
        """
        try:
            return self._auth_headers()
        except Exception as e:
            logger.debug(
                f'[ParamManager: {self._instance_name}] Leitura sem '
                f'autenticação: {e}'
            )
            return {}

    def create_app(self, name: str, description: str | None = None):
        url = f'{self._api_base_url}/parameters/apps/'

        payload = {'name': name, 'description': description}

        res = requests.post(
            url,
            json=payload,
            headers=self._auth_headers(),
            timeout=self._timeout,
        )

        if res.status_code != HTTPStatus.CREATED:
            raise Exception(f'Erro ao criar app: {res.text}')

        return res.json()

    def upsert_params(  # noqa: PLR0913 PLR0917
        self,
        app_name: str,
        param_name: str,
        *,
        value: Any,
        param_type: str,
        description: str | None = None,
        # None (e não False) para que a chave seja OMITIDA do payload
        # quando o chamador não informa. É isso que permite ao servidor
        # distinguir "não enviado" de "enviado como False" e destravar
        # a edição de parâmetros user_editable por usuário comum.
        user_editable: bool | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        min_value: int | float | None = None,
        max_value: int | float | None = None,
        referenced_params: list[str] | None = None,
    ):
        payload = {
            param_name: {
                'value': value,
                'type': param_type,
            }
        }

        optional_fields = {
            'description': description,
            'user_editable': user_editable,
            'min_length': min_length,
            'max_length': max_length,
            'min_value': min_value,
            'max_value': max_value,
            'referenced_params': referenced_params,
        }
        payload[param_name].update({
            key: val for key, val in optional_fields.items() if val is not None
        })
        url = f'{self._api_base_url}/parameters/apps/{app_name}/params/'

        def _do_request():
            return requests.put(
                url,
                json=payload,
                headers=self._auth_headers(),
                timeout=self._timeout,
            )

        res = _do_request()

        # Se não autorizado, tenta renovar token e repetir
        if res.status_code == HTTPStatus.UNAUTHORIZED:
            self._force_token_refresh()
            time.sleep(2)
            res = _do_request()

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao fazer upsert de parâmetros: {res.text}')

        self._cache[app_name] = res.json().get('params', {})
        self._cache_timestamp[app_name] = time.time()
        # Invalida cache por parâmetro; ver delete_param para a ordem.
        self.clear_cache(app_name, param_name)
        self._save_to_local_db(app_name, self._cache[app_name])

        return res.json()

    def delete_param(self, app_name: str, param_name: str):
        url = (
            f'{self._api_base_url}/parameters/apps/'
            f'{app_name}/params/{param_name}'
        )

        res = requests.delete(
            url, headers=self._auth_headers(), timeout=self._timeout
        )

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao deletar parâmetro: {res.text}')

        # Remove do cache local
        if app_name in self._cache:
            self._cache[app_name].pop(param_name, None)

        # Invalida cache por parâmetro. Deve vir ANTES de
        # _remove_from_local_db para evitar que um get_param concorrente
        # repopule _param_cache a partir de um _cache ainda sujo.
        # Chamar clear_cache de dentro de _remove_from_local_db seria
        # deadlock: aquele método segura self._lock, que é threading.Lock
        # (não RLock), enquanto clear_cache não adquire lock.
        self.clear_cache(app_name, param_name)

        # Remoção explícita: o merge de _save_to_local_db ressuscitaria
        # a chave a partir do registro anterior, e o parâmetro apagado
        # — possivelmente uma credencial revogada — seguiria sendo
        # servido pelo fallback offline.
        self._remove_from_local_db(app_name, param_name)

        return res.json()

    def delete_app(self, app_name: str):
        url = f'{self._api_base_url}/parameters/apps/{app_name}'

        res = requests.delete(
            url, headers=self._auth_headers(), timeout=self._timeout
        )

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao deletar app: {res.text}')
        self.clear_cache(app_name)

        return res.json()

    @staticmethod
    def _is_encrypted_param(param: Any) -> bool:
        """
        Diz se um parâmetro sensível ainda está com o valor cifrado.

        Parâmetros de tipo não sensível são sempre considerados seguros
        para persistir.
        """
        if not isinstance(param, dict):
            return True

        tipo = param.get('type')
        value = param.get('value')

        if tipo == 'secret':
            return _is_envelope(value)
        if tipo == 'user':
            return isinstance(value, dict) and _is_envelope(
                value.get('password')
            )
        if tipo == 'users':
            return isinstance(value, list) and all(
                isinstance(item, dict) and _is_envelope(item.get('password'))
                for item in value
            )
        return True

    @staticmethod
    def _process_parameters(params: dict) -> dict:
        """
        Devolve os parâmetros com os valores sensíveis decifrados.

        Para `secret`, `user` e `users` devolve uma cópia profunda — é
        o que garante que o texto claro nunca alcance o cache nem o
        banco local. Tipos não sensíveis são devolvidos POR REFERÊNCIA:
        o dict retornado é o mesmo objeto guardado em `self._cache`, e
        mutá-lo altera o cache do processo.
        """
        return {
            key: ParamManager._process_parameter(param)
            for key, param in params.items()
        }

    @staticmethod
    def _process_parameter(params: dict) -> dict | None:
        """
        Decifra um parâmetro sensível devolvendo uma cópia.

        Tipos fora de SENSITIVE_TYPES são devolvidos como vieram, sem
        cópia — ver a nota de aliasing em `_process_parameters`.
        """
        if not isinstance(params, dict):
            return params

        if params.get('type') not in SENSITIVE_TYPES:
            return params

        params = copy.deepcopy(params)

        if params.get('type') == 'secret':
            raw = params.get('value')
            if isinstance(raw, dict):
                params['value'] = ParamManager._descriptografar_param(raw)
        elif params.get('type') == 'users':
            raw = params.get('value')
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and isinstance(
                        item.get('password'), dict
                    ):
                        item['password'] = ParamManager._descriptografar_param(
                            item['password']
                        )
        elif params.get('type') == 'user':
            raw = params.get('value')
            if isinstance(raw, dict):
                if isinstance(raw.get('password'), dict):
                    raw['password'] = ParamManager._descriptografar_param(
                        raw['password']
                    )
        return params

    @staticmethod
    def _extract_value(param_value: dict) -> Any:
        if not isinstance(param_value, dict):
            return None
        if param_value.get('type') in SENSITIVE_TYPES:
            param_value = ParamManager._process_parameter(param_value)
        return param_value.get('value')

    @staticmethod
    def _descriptografar_param(value: dict) -> str | None:
        try:
            if not all(
                k in value for k in ['salt', 'master_key', 'crypto_data']
            ):
                return None

            app_custody_key = os.getenv('CHAVE_CUSTODIA_APP') or os.getenv(
                'APP_CUSTODY_KEY'
            )
            if not app_custody_key:
                logger.error(
                    '🔐 CHAVE_CUSTODIA_APP não está definida no ambiente.'
                )
                return None

            salt = bytes.fromhex(value['salt'])
            chave_custodia = PBKDF2(
                app_custody_key.encode(),
                salt,
                dkLen=32,
                count=100_000,
                hmac_hash_module=SHA256,
            )

            cm_iv = bytes.fromhex(value['master_key']['iv'])
            cm_tag = bytes.fromhex(value['master_key']['tag'])

            cm_data = bytes.fromhex(
                value['master_key'].get('data')
                or value['master_key'].get('dado')
            )

            cipher_cm = AES.new(chave_custodia, AES.MODE_GCM, cm_iv)
            chave_mestra = cipher_cm.decrypt_and_verify(cm_data, cm_tag)

            pw_iv = bytes.fromhex(value['crypto_data']['iv'])
            pw_tag = bytes.fromhex(value['crypto_data']['tag'])
            pw_data = bytes.fromhex(
                value['crypto_data'].get('data')
                or value['crypto_data'].get('dado')
            )
            cipher_pw = AES.new(chave_mestra, AES.MODE_GCM, pw_iv)
            senha = cipher_pw.decrypt_and_verify(pw_data, pw_tag)

            return senha.decode()
        except Exception as e:
            logger.error(
                f'Erro ao descriptografar parâmetro secreto: {str(e)}'
            )
            return None

    def get_all_params(self, app_name: str) -> Dict[str, Any]:
        logger.info(f'Solicitando todos os parâmetros para o app: {app_name}')
        if self._is_cache_valid(app_name):
            logger.info(f'Usando cache para o app: {app_name}')
            return ParamManager._process_parameters(self._cache[app_name])
        if self._is_api_error_cached(app_name):
            logger.warning(
                f'API para {app_name} está em cooldown.'
                f'Usando dados locais ou cache.'
            )
            return ParamManager._process_parameters(
                self._get_from_local_db(app_name)
            )

        try:
            params = self._fetch_from_api(app_name)
            return ParamManager._process_parameters(params)
        except ParamNaoEncontradoError as e:
            logger.warning(
                f'Parâmetros não encontrados (404) para {app_name}: '
                f'{str(e)}'
            )
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )
        except (Timeout, ConnectionError) as e:
            logger.error(f'Erro de conexão/timeout: {str(e)}')
            self._armar_breaker(app_name)
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )
        except Exception as e:
            logger.error(f'Erro inesperado ao buscar da API: {str(e)}')
            # Erro HTTP também precisa armar o cooldown, senão a lib
            # martela um servidor que está devolvendo 500.
            self._armar_breaker(app_name)
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )

    def get_param(  # noqa: PLR0911
        self, app_name: str, param_name: str, save_cache: bool = True
    ) -> Any:
        logger.info(
            f'Solicitando parâmetro {param_name} para o app: {app_name}'
        )
        param_cache_key = f'{app_name}:{param_name}'

        # Verifica cache específico
        if self._is_param_cache_valid(app_name, param_name):
            logger.info(
                f'Usando cache específico para o parâmetro:'
                f' {param_name} do app: {app_name}'
            )
            return ParamManager._extract_value(
                self._param_cache[param_cache_key]
            )
        if self._is_cache_valid(app_name):
            logger.info(
                f'Usando cache global do app para o parâmetro: {param_name}'
            )
            params = self._cache[app_name]
            param_value = params.get(param_name)
            if param_value is not None:
                self._param_cache[param_cache_key] = param_value
                self._param_cache_timestamp[param_cache_key] = time.time()
                return ParamManager._extract_value(param_value)
        if self._is_api_error_cached(app_name):
            logger.warning(
                f'API para {app_name} está em cooldown. Usando dados locais.'
            )
            params = self._get_from_local_db(app_name, param_name)
            return (
                ParamManager._extract_value(params.get(param_name, dict()))
                if params
                else None
            )
        try:
            param_value = self._fetch_param_from_api(
                app_name, param_name, save_cache
            )
            if not isinstance(param_value, dict):
                param_value = dict()
            return ParamManager._extract_value(param_value)
        except ParamNaoEncontradoError as e:
            logger.warning(
                f'Parâmetro não encontrado (404) na API:'
                f'{app_name=} {param_name=} {save_cache=} {str(e)}'
            )
            params = self._handle_api_error(app_name, param_name, e)
            return (
                ParamManager._extract_value(params.get(param_name, dict()))
                if params
                else None
            )
        except (Timeout, ConnectionError) as e:
            logger.error(
                f'Erro de conexão/timeout ao buscar parâmetro da API:'
                f'{app_name=} {param_name=} {save_cache=} {str(e)}'
            )
            self._armar_breaker(app_name)
            params = self._handle_api_error(app_name, param_name, e)
            return (
                ParamManager._extract_value(params.get(param_name, dict()))
                if params
                else None
            )
        except Exception as e:
            logger.error(
                f'Erro inesperado ao buscar parâmetro da API:'
                f'{app_name=} {param_name=} {save_cache=} {str(e)}'
            )
            self._armar_breaker(app_name)
            params = self._handle_api_error(app_name, param_name, e)
            return (
                ParamManager._extract_value(params.get(param_name, dict()))
                if params
                else None
            )

    def _fetch_from_api(
        self,
        app_name: str,
        save_cache: bool = True,
    ) -> Dict[str, Any]:
        url = f'{self._api_base_url}/parameters/apps/{app_name}/params/'
        logger.info(f'Buscando todos os parâmetros da API: {url}')

        response = requests.get(
            url,
            timeout=self._timeout,
            verify=self._verify_ssl,
            headers=self._auth_headers_opcionais(),
        )

        if response.status_code == HTTPStatus.NOT_FOUND:
            raise ParamNaoEncontradoError(
                f'API retornou status code {response.status_code}'
            )
        if response.status_code != HTTPStatus.OK:
            raise Exception(f'API retornou status code {response.status_code}')

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            logger.error(
                f'Erro de JSON na resposta da API para {app_name}: {e}'
            )
            try:
                self._db.drop_table(app_name)
                logger.warning(
                    f"Tabela local do app '{app_name}' foi limpa após "
                    f'erro de parsing da API.'
                )
            except Exception as purge_err:
                logger.error(f'Falha ao limpar DB local: {purge_err}')
            return {}

        params = data.get('params', {})

        self._cache[app_name] = params
        self._cache_timestamp[app_name] = time.time()

        if save_cache:
            self._save_to_local_db(app_name, params)

        if app_name in self._api_error_timestamp:
            del self._api_error_timestamp[app_name]

        return params

    def _fetch_param_from_api(
        self, app_name: str, param_name: str, save_cache: bool = True
    ) -> Any:
        url = (
            f'{self._api_base_url}/parameters/apps/'
            f'{app_name}/params/{param_name}'
        )
        logger.info(f'Buscando parâmetro específico da API: {url}')
        response = requests.get(
            url,
            timeout=self._timeout,
            verify=self._verify_ssl,
            headers=self._auth_headers_opcionais(),
        )
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise ParamNaoEncontradoError(
                f'API retornou status code {response.status_code}'
            )
        if response.status_code != HTTPStatus.OK:
            raise Exception(f'API retornou status code {response.status_code}')
        data = response.json()
        param_value = data.get('param')
        if save_cache:
            param_cache_key = f'{app_name}:{param_name}'
            self._param_cache[param_cache_key] = param_value
            self._param_cache_timestamp[param_cache_key] = time.time()
            if app_name in self._cache:
                self._cache[app_name][param_name] = param_value
            else:
                self._cache[app_name] = {param_name: param_value}
            self._save_to_local_db(app_name, self._cache[app_name])
        if app_name in self._api_error_timestamp:
            del self._api_error_timestamp[app_name]

        return param_value

    def _is_cache_valid(self, app_name: str) -> bool:
        if (
            app_name not in self._cache
            or app_name not in self._cache_timestamp
        ):
            return False
        current_time = time.time()
        cache_time = self._cache_timestamp[app_name]

        return (current_time - cache_time) < self._cache_duration

    def _is_param_cache_valid(self, app_name: str, param_name: str) -> bool:
        param_cache_key = f'{app_name}:{param_name}'
        if (
            param_cache_key not in self._param_cache
            or param_cache_key not in self._param_cache_timestamp
        ):
            return False
        current_time = time.time()
        cache_time = self._param_cache_timestamp[param_cache_key]

        return (current_time - cache_time) < self._cache_duration

    @property
    def _effective_cooldown(self) -> int:
        """Janela do circuit breaker, com fallback vivo."""
        if self._api_error_cooldown is not None:
            return self._api_error_cooldown
        return self._cache_duration

    def _armar_breaker(self, app_name: str) -> None:
        """Arma o circuit breaker para um app."""
        self._api_error_timestamp[app_name] = time.time()

    def _is_api_error_cached(self, app_name: str) -> bool:
        if app_name not in self._api_error_timestamp:
            return False

        current_time = time.time()
        error_time = self._api_error_timestamp[app_name]
        return (current_time - error_time) < self._effective_cooldown

    def _get_from_local_db(
        self, app_name: str, param_name: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.info(f'Buscando parâmetros localmente para o app: {app_name}')
        try:
            table = self._db.table(app_name)
            records = table.all()
            if not records:
                logger.warning(
                    f'Nenhum registro local encontrado para o app: {app_name}'
                )
                return {}
            records.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            params = records[0].get('params', {})
            if param_name:
                return (
                    {param_name: params[param_name]}
                    if param_name in params
                    else {}
                )
            return params
        except Exception as e:
            logger.error(f'Erro ao ler DB local para {app_name}: {e}')
            try:
                # drop_table (e não drop_tables): este caminho roda
                # durante indisponibilidade da API, quando o fallback
                # offline é o que resta. Um registro ilegível de um app
                # não pode apagar o cache de todos os outros.
                self._db.drop_table(app_name)
                logger.warning(
                    f"Tabela local do app '{app_name}' foi limpa após "
                    f'erro de leitura.'
                )
            except Exception as purge_err:
                logger.error(f'Falha ao limpar DB local: {purge_err}')
            return {}

    def _handle_api_error(
        self, app_name: str, param_name: Optional[str], error: Exception
    ) -> Dict[str, Any]:
        logger.error(f'Erro ao acessar API para {app_name}: {str(error)}')
        logger.info(f'Tentando usar dados locais para {app_name}')
        return self._get_from_local_db(app_name, param_name)

    def get_cache_info(self) -> Dict[str, Any]:
        info = {
            'apps_cached': list(self._cache.keys()),
            'cache_timestamps': {},
            'cache_valid': {},
            'params_cached': [],
            'param_cache_timestamps': {},
            'param_cache_valid': {},
            'api_error_timestamps': {},
        }

        for app_name, timestamp in self._cache_timestamp.items():
            dt = datetime.fromtimestamp(timestamp)
            expires_at = dt + timedelta(seconds=self._cache_duration)
            is_valid = self._is_cache_valid(app_name)

            info['cache_timestamps'][app_name] = {
                'cached_at': dt.isoformat(),
                'expires_at': expires_at.isoformat(),
                'seconds_remaining': int(
                    timestamp + self._cache_duration - time.time()
                )
                if is_valid
                else 0,
            }
            info['cache_valid'][app_name] = is_valid
        for param_key, timestamp in self._param_cache_timestamp.items():
            info['params_cached'].append(param_key)

            dt = datetime.fromtimestamp(timestamp)
            expires_at = dt + timedelta(seconds=self._cache_duration)

            # Extrai app_name e param_name da chave
            app_name, param_name = param_key.split(':', 1)
            is_valid = self._is_param_cache_valid(app_name, param_name)

            info['param_cache_timestamps'][param_key] = {
                'cached_at': dt.isoformat(),
                'expires_at': expires_at.isoformat(),
                'seconds_remaining': int(
                    timestamp + self._cache_duration - time.time()
                )
                if is_valid
                else 0,
            }
            info['param_cache_valid'][param_key] = is_valid
        for app_name, timestamp in self._api_error_timestamp.items():
            dt = datetime.fromtimestamp(timestamp)
            cooldown_ends_at = dt + timedelta(
                seconds=self._effective_cooldown
            )
            is_cooldown_active = self._is_api_error_cached(app_name)

            info['api_error_timestamps'][app_name] = {
                'error_at': dt.isoformat(),
                'cooldown_ends_at': cooldown_ends_at.isoformat(),
                'cooldown_remaining_seconds': int(
                    (
                        cooldown_ends_at - datetime.fromtimestamp(time.time())
                    ).total_seconds()
                )
                if is_cooldown_active
                else 0,
            }

        return info
