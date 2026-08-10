from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, ClassVar, Dict, Optional, Tuple

import requests
from dotenv import find_dotenv, load_dotenv
from requests.exceptions import ConnectionError, Timeout
from tinydb import TinyDB

# Reexportados: `from param_manager.manager import ParamNaoEncontradoError`
# é o caminho que o __init__ e código de terceiros usam desde antes da
# decomposição. Mover a definição sem reexportar seria quebra.
from param_manager.crypto import (  # noqa: F401
    ENVELOPE_KEYS,
    SENSITIVE_TYPES,
    _decrypt_param,
    _extract_value,
    _is_encrypted_param,
    _is_envelope,
    _process_parameter,
    _process_parameters,
)
from param_manager.errors import (  # noqa: F401
    ParamNaoEncontradoError,
    ParamNotFoundError,
)
from param_manager.local_store import (
    ESTADO_DIRTY,
    ESTADO_DRAFT,
    LocalStore,
    LocalStoreError,
)
from param_manager.type_catalog import CATALOGO_EMBARCADO, validar_advisory

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('ParamManager')

# Posicao de instance_name na assinatura posicional de __init__.
INSTANCE_NAME_ARG_POSITION = 6

# Modos de execução.
#
# `remote` é o default e reproduz o comportamento publicado byte a byte:
# quem não pedir nada não percebe que este eixo existe. `local` grava
# direto no sidecar, sem API nenhuma.
#
# Não existe `hybrid`: ele triplicaria a máquina de estados, e o
# comportamento híbrido útil — lê do servidor, cai no local quando ele
# some — JÁ É o modo remoto, via circuit breaker.
MODO_REMOTO = 'remote'
MODO_LOCAL = 'local'
MODOS_VALIDOS = frozenset({MODO_REMOTO, MODO_LOCAL})


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

    # PLR0915: o corpo passou de 50 sentenças ao ser envolvido no
    # try/except que descarta a instância meio-construída (R7). Quebrar
    # a resolução de configuração em outro método só moveria o problema
    # e deixaria dois lugares para procurar.
    def __init__(  # noqa: PLR0913, PLR0917, PLR0915
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
        # keyword-only e DEPOIS de todos os posicionais: __new__ deriva
        # instance_name de args[INSTANCE_NAME_ARG_POSITION], então um
        # parâmetro posicional novo antes daquela posição registraria a
        # instância no slot errado do multiton.
        *,
        mode: str | None = None,
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

            try:
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
                    negative_becomes=0,
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
                # Lock para os dicts de cache e breaker (CL-2): protege
                # _cache, _cache_timestamp, _param_cache,
                # _param_cache_timestamp, _api_error_timestamp.
                self._state_lock = threading.Lock()
                self._token = None
                self._refresh_token = None
                self._token_expire_at = 0
                # Quem está com a vez de renovar o token. Ver
                # _sync_get_new_token.
                self._token_renewing = False
                # Negativo aqui já é caminho quebrado (o requests estoura),
                # então cai no fallback, ao contrário de CACHE_DURATION.
                self._timeout = self._resolve_int_env(
                    os.getenv('TIMEOUT'), 'TIMEOUT', timeout
                )
                # Janela do circuit breaker. Sem argumento e sem env var
                # cai em _cache_duration, que era o valor implícito antes
                # — com get_instance isso são 3600s, e um único 500
                # transitório prendia o cliente em dado local por 1 hora.
                raw_cooldown = (
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
                    raw_cooldown, 'API_ERROR_COOLDOWN', None
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

                # Modo de execução. Mesmos três degraus de precedência de
                # todo o resto — argumento > env prefixada > env global —,
                # então NÃO é uma quarta fonte de configuração.
                self._mode = self._resolve_mode(mode, instance_name)

                # O sidecar só é aberto no modo local: quem roda em
                # remoto não paga um segundo handle de TinyDB nem um
                # arquivo a mais no disco.
                self._local_store = (
                    LocalStore(
                        os.path.join(
                            db_dir, f'local_{self._instance_name}.json'
                        ),
                        self._lock,
                        self._instance_name,
                    )
                    if self._mode == MODO_LOCAL
                    else None
                )

                self._cache = {}
                self._cache_timestamp = {}
                self._param_cache = {}
                self._param_cache_timestamp = {}
                self._api_error_timestamp = {}

                self._purge_plaintext_cache()

                self._initialized = True
                logger.info(
                    f'[ParamManager: {self._instance_name}] '
                    f'Inicializado na API: {self._api_base_url}'
                )
            except Exception as e:
                self._discard_failed_instance(instance_name, e)
                raise

    def _discard_failed_instance(self, instance_name, error):
        """
        Tira do multiton a instância que não terminou de nascer.

        Sem isto, o objeto meio-construído fica em `_instances` e toda
        chamada seguinte a `get_instance` devolve o mesmo objeto
        quebrado — o processo não se recupera sozinho.

        Fechar o TinyDB já aberto é parte da limpeza, não detalhe:
        deixá-lo aberto troca a instância morta por um arquivo travado
        no Windows, que sobrevive às novas tentativas e é pior.
        """
        logger.error(
            f'[ParamManager: {instance_name}] '
            f'Falha na inicialização: {error}'
        )
        self.__class__._instances.pop(instance_name, None)

        if getattr(self, '_db', None) is not None:
            try:
                self._db.close()
            except Exception as close_error:
                logger.error(
                    f'Falha ao fechar o banco local na limpeza: '
                    f'{close_error}'
                )

        # O sidecar é o segundo handle e precisa do mesmo cuidado: se a
        # falha aconteceu depois de abri-lo, deixá-lo pendurado trava o
        # arquivo do rascunho no Windows.
        if getattr(self, '_local_store', None) is not None:
            try:
                self._local_store.close()
            except Exception as close_error:
                logger.error(
                    f'Falha ao fechar o arquivo local na limpeza: '
                    f'{close_error}'
                )

    @staticmethod
    def _resolve_mode(mode: str | None, instance_name: str) -> str:
        """
        Resolve o modo na precedência padrão da lib:
        construtor > {INSTANCE}_PARAM_MANAGER_MODE > PARAM_MANAGER_MODE.

        Valor irreconhecível cai em `remote` com aviso, em vez de
        derrubar a construção — mesma escolha de `_resolve_int_env`. E
        cair para `remote` é a direção segura: `local` deixaria a
        aplicação lendo rascunho sem que ninguém tivesse pedido.

        **Ausência de URL NÃO liga o modo local.** Hoje, sem URL, a
        leitura falha para o banco local e devolve `{}`; transformar
        isso em "entra em local e passa a aceitar escrita" mudaria o
        comportamento observável de quem roda sem URL por engano.
        """
        raw = mode
        if raw is None:
            raw = os.getenv(
                f'{instance_name.upper()}_PARAM_MANAGER_MODE',
                os.getenv('PARAM_MANAGER_MODE'),
            )
        if raw is None:
            return MODO_REMOTO

        normalizado = str(raw).strip().lower()
        if normalizado not in MODOS_VALIDOS:
            logger.warning(
                f'[ParamManager: {instance_name}] Modo {raw!r} não '
                f'reconhecido; usando {MODO_REMOTO!r}. Válidos: '
                f'{sorted(MODOS_VALIDOS)}.'
            )
            return MODO_REMOTO
        return normalizado

    @property
    def mode(self) -> str:
        """Modo efetivo desta instância. Somente leitura."""
        return self._mode

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
            raw = os.getenv(
                f'{instance_name.upper()}_VERIFY_SSL',
                os.getenv('VERIFY_SSL'),
            )
            if raw is None:
                verify_ssl = False
            else:
                verify_ssl = raw.strip().lower() in {
                    '1',
                    'true',
                    'yes',
                    'on',
                }
        return verify_ssl

    @staticmethod
    def _resolve_int_env(  # noqa: PLR0913, PLR0917
        raw: int | str | None,
        name: str,
        fallback: int | None,
        negative_becomes: int | None = None,
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

        `negative_becomes` existe para CACHE_DURATION, onde o padrão seria
        perigoso: hoje um valor negativo faz `_is_cache_valid` devolver
        sempre False, ou seja, nunca cacheia. Mandá-lo para o fallback
        transformaria "nunca cacheia" em "cacheia por uma hora" — um
        afrouxamento silencioso numa biblioteca que serve `secret`.
        Mapeando para 0, o comportamento observável fica idêntico.
        """
        if raw is None:
            return fallback

        value = None
        fallback_reason = None
        is_negative = False

        # Já é int: validar sinal
        if isinstance(raw, int):
            if raw < 0:
                is_negative = True
                fallback_reason = f'é negativo ({raw})'
            else:
                value = raw
        else:
            # String: strip e tentar int
            try:
                stripped = raw.strip()
                if not stripped:
                    fallback_reason = 'vazio'
                else:
                    value = int(stripped)
                    if value < 0:
                        is_negative = True
                        fallback_reason = f'é negativo ({value})'
                        value = None
            except (ValueError, AttributeError) as e:
                fallback_reason = f'inválido ({raw!r}): {e}'

        if fallback_reason is not None:
            if is_negative and negative_becomes is not None:
                logger.warning(
                    f'[ParamManager] {name} {fallback_reason}; '
                    f'usando {negative_becomes}.'
                )
                return negative_becomes
            logger.warning(
                f'[ParamManager] {name} {fallback_reason}; usando fallback.'
            )
            return fallback

        return value

    def _snapshot_cache(self, app: str) -> Dict[str, Any]:
        """
        Retorna cópia rasa do cache de um app (CAS/R1).

        Copiar o container nunca as folhas: o dict retornado é novo,
        mas contém as mesmas referências de objeto que estavam em
        self._cache[app]. Iterações sobre o snapshot não estouram com
        RuntimeError mesmo se a thread concorrente modificar o original.
        O aliasing das folhas em _process_parameters (tipos não
        sensíveis) é comportamento observável e documentado — preservado.
        """
        with self._state_lock:
            return dict(self._cache.get(app, {}))

    def _publish_cache(
        self, app: str, params: Dict[str, Any], started_at: float
    ) -> None:
        """
        Atualiza cache apenas se não foi escrito mais recentemente (CAS).

        Impede que uma resposta atrasada sobrescreva cache mais novo.
        """
        with self._state_lock:
            if self._cache_timestamp.get(app, 0) <= started_at:
                self._cache[app] = params
                self._cache_timestamp[app] = started_at

    def _arm_breaker(self, app_name: str) -> None:
        """Arma o circuit breaker para um app."""
        with self._state_lock:
            self._api_error_timestamp[app_name] = time.time()

    def _disarm_breaker(self, app: str, started_at: float) -> None:
        """
        Desarma o breaker apenas se foi armado antes desta requisição (CAS).

        Impede que uma resposta atrasada (de antes do erro) destrua o
        registro do erro e abra o circuito prematuramente.

        O empate desarma, de propósito. `time.time()` tem resolução de
        ~15 ms no Windows, então um erro e uma requisição iniciada no
        mesmo tique recebem o mesmo timestamp. Os dois lados do empate
        custam coisas muito diferentes: desarmar cedo demais gasta uma
        requisição a mais, que no pior caso rearma o breaker; deixar de
        desarmar prende o cliente no fallback local pelo cooldown
        inteiro — 3600s com os defaults de `get_instance`. Por isso a
        comparação é `<=` e não `<`.
        """
        with self._state_lock:
            if self._api_error_timestamp.get(app, 0) <= started_at:
                self._api_error_timestamp.pop(app, None)

    def _breaker_active(self, app: str) -> bool:
        """Diz se o circuit breaker está ativo para este app."""
        with self._state_lock:
            if app not in self._api_error_timestamp:
                return False
            current_time = time.time()
            error_time = self._api_error_timestamp[app]
            return (current_time - error_time) < self._effective_cooldown

    def _snapshot_info(self) -> Tuple[Dict, Dict, Dict]:
        """
        Cópia dos três dicts de timestamp (CAS/R1).

        Para get_cache_info iterar fora do lock sem estouro de
        RuntimeError.
        """
        with self._state_lock:
            return (
                dict(self._cache_timestamp),
                dict(self._param_cache_timestamp),
                dict(self._api_error_timestamp),
            )

    def _purge_plaintext_cache(self) -> None:
        """
        Remove do banco local valores sensíveis gravados em claro por
        versões anteriores. Opt-in: default desligado.

        Roda durante __init__ sob _lock_singleton, depois de self._lock
        ser criado (linha 140).
        """
        raw = os.getenv(
            f'{self._instance_name.upper()}_PURGE_PLAINTEXT_CACHE',
            os.getenv('PARAM_MANAGER_PURGE_PLAINTEXT_CACHE', ''),
        )
        if raw.strip().lower() not in {'1', 'true', 'yes', 'on'}:
            return

        try:
            with self._lock:
                for app_name in list(self._db.tables()):
                    table = self._db.table(app_name)
                    record = table.get(doc_id=1)
                    if not record or not isinstance(
                        record.get('params'), dict
                    ):
                        continue
                    cleaned = self._discard_unencrypted(
                        app_name, record['params']
                    )
                    if len(cleaned) != len(record['params']):
                        table.update({'params': cleaned}, doc_ids=[1])
                        logger.warning(
                            f'[ParamManager: {self._instance_name}] '
                            f'Valores em claro removidos do cache '
                            f"local de '{app_name}'."
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
                record = table.get(doc_id=1)
                if not record or not isinstance(
                    record.get('params'), dict
                ):
                    return
                if param_name not in record['params']:
                    return
                record['params'].pop(param_name)
                table.update({'params': record['params']}, doc_ids=[1])
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

        safe_params = {}
        for key, param in params.items():
            if ParamManager._is_encrypted_param(param):
                safe_params[key] = param
                continue
            logger.warning(
                f'[ParamManager: {self._instance_name}] Parâmetro sensível '
                f"'{key}' do app '{app_name}' não está cifrado; "
                f'descartado da persistência local.'
            )
        return safe_params

    def clear_cache(
        self, app_name: Optional[str] = None, param_name: Optional[str] = None
    ) -> None:
        """
        Limpa apenas o cache desta instância.
        """
        with self._state_lock:
            if app_name and param_name:
                key = f'{app_name}:{param_name}'
                self._param_cache.pop(key, None)
                self._param_cache_timestamp.pop(key, None)
            elif app_name:
                self._cache.pop(app_name, None)
                self._cache_timestamp.pop(app_name, None)
                # IMPORTANTE: clear_cache é ação explícita do operador
                # e desarma o breaker incondicionalmente. O desarme por
                # sucesso de requisição é CAS-guardado em _disarm_breaker
                # — duas semânticas diferentes sobre o mesmo dict. Sem este
                # comentário, o próximo leitor "uniformiza" e reintroduz a
                # race do desarme precoce (R5).
                self._api_error_timestamp.pop(app_name, None)
                # Limpa chaves específicas que começam com o app
                keys_to_del = [
                    k
                    for k in self._param_cache
                    if k.startswith(f'{app_name}:')
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
        """
        Faz POST em /auth/token e retorna (token, refresh_token, expire_at).

        **Rede fora do lock.** Atualização de estado acontece no chamador.
        """
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
        token = auth_data.get('access_token')
        refresh = auth_data.get('refresh_token')

        # token TTL: 30 min
        expire_at = time.time() + 29 * 60

        return token, refresh, expire_at

    def _auth_refresh_token(self):
        """
        Faz POST em /auth/refresh e retorna (token, refresh_token, expire_at).

        **Rede fora do lock.** Atualização de estado acontece no chamador.

        Se refresh falhar, retorna None para sinalizar que é preciso
        fazer um get novo.
        """
        if not self._refresh_token:
            return None

        url = f'{self._api_base_url}/auth/refresh'

        data = {
            'refresh_token': self._refresh_token,
        }

        res = requests.post(url, data=data, timeout=self._timeout)

        if res.status_code != HTTPStatus.OK:
            return None

        auth_data = res.json()
        token = auth_data.get('access_token')
        refresh = auth_data.get('refresh_token')

        expire_at = time.time() + 29 * 60

        return token, refresh, expire_at

    def _get_valid_token(self):
        """
        Retorna token válido: se não há, faz autenticação; se expirado,
        renova. **Leitura atômica do par (_token, _token_expire_at)**.

        Double-checked locking: a leitura rápida pode perder uma requisição
        em race, mas apenas uma thread realmente faz rede.

        Rede (POST) acontece FORA do lock para não bloquear outros acessos.
        """
        # O par é lido junto: separado, uma thread podia pegar o token
        # novo com a expiração antiga (ou o contrário) e devolver como
        # válido um token já vencido por até 29 minutos.
        with self._token_lock:
            token = self._token
            expire_at = self._token_expire_at
        if token and time.time() < expire_at:
            return token

        return self._sync_get_new_token(token)

    def _sync_get_new_token(self, seen_token):
        """
        Renova o token com apenas uma ida à rede, por mais threads que
        cheguem juntas.

        `seen_token` é o token que o chamador tinha em mãos quando
        decidiu renovar. Se, ao pegar a vez, o token guardado já for
        outro, alguém renovou no intervalo e o resultado dessa
        renovação serve — é o que preserva o double-checked locking.
        Sem essa conferência, N threads que chegam com o token expirado
        renovam **em série**, uma ida à rede cada, e no Keycloak padrão
        o refresh token é de uso único: a segunda invalidaria a sessão
        que a primeira acabou de abrir.

        A vez é dada por uma flag, e não por um segundo lock, porque um
        lock aqui teria de ser segurado junto com `_token_lock` e
        quebraria a regra `no-nesting` que CL-4 verifica. A rede
        acontece fora de `_token_lock` para que ninguém que só queira
        *ler* o par (token, expiração) fique preso atrás de um POST.
        """
        while True:
            with self._token_lock:
                if self._token is not None and self._token != seen_token:
                    return self._token
                if not self._token_renewing:
                    self._token_renewing = True
                    needs_get = not self._token
                    break
            time.sleep(0.001)

        try:
            # Rede FORA do lock
            if needs_get:
                token, refresh, expire_at = self._auth_get_token()
            else:
                result = self._auth_refresh_token()
                if result is None:
                    token, refresh, expire_at = self._auth_get_token()
                else:
                    token, refresh, expire_at = result

            # Atualiza estado sob lock (escrita atômica)
            with self._token_lock:
                self._token = token
                self._refresh_token = refresh
                self._token_expire_at = expire_at

            return token
        finally:
            # Libera a vez para as threads que estão esperando.
            with self._token_lock:
                self._token_renewing = False

    def _force_token_refresh(self):
        """
        Força renovação do token de forma sincronizada.

        Chamar `_auth_refresh_token()` direto no retry de 401 furava o
        double-checked locking: duas threads em 401 simultâneo fariam
        `POST /auth/refresh` com o mesmo refresh token — de uso único
        no Keycloak padrão —, e a segunda invalidaria a sessão que a
        primeira acabou de renovar.

        Passa o token que este chamador viu, e não a expiração: num 401
        o token pode estar dentro da validade e mesmo assim ter sido
        recusado, então o critério de "alguém já resolveu" é o token
        ter mudado, não ter vencido.
        """
        with self._token_lock:
            seen_token = self._token
        return self._sync_get_new_token(seen_token)

    def _auth_headers(self):
        token = self._get_valid_token()
        return {'Authorization': f'Bearer {token}'}

    def _auth_headers_optional(self) -> Dict[str, str]:
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

    def _type_catalog(self) -> Dict[str, Any]:
        """
        Catálogo em uso: o guardado do servidor, senão o embarcado.

        O embarcado envelhece de propósito — é o que sobra quando não há
        servidor. `refresh_type_catalog()` é como se atualiza.
        """
        if self._local_store is not None:
            guardado = self._local_store.catalogo()
            if guardado:
                return guardado
        return CATALOGO_EMBARCADO

    def refresh_type_catalog(self) -> Dict[str, Any]:
        """
        Busca o catálogo de tipos no servidor e o guarda para uso offline.

        ADITIVO. Precisa de rede, então roda antes de perder o servidor
        de vista — tipicamente uma vez, ao preparar a máquina para
        trabalhar em modo local.

        Sem autenticação: a rota é descrição estática do esquema, e
        exigir token justamente aqui derrotaria o propósito.
        """
        url = f'{self._api_base_url}/parameters/types'
        res = requests.get(
            url, timeout=self._timeout, verify=self._verify_ssl
        )
        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao buscar catálogo de tipos: {res.text}')

        catalogo = res.json()
        if self._local_store is not None:
            self._local_store.guardar_catalogo(catalogo)
        else:
            logger.info(
                f'[ParamManager: {self._instance_name}] Catálogo obtido, '
                f'mas não guardado: só o modo local mantém sidecar.'
            )
        return catalogo

    def _params_locais(self, app_name: str) -> Dict[str, Any]:
        """Parâmetros do app no sidecar, na forma `{nome: payload}`."""
        return {
            registro['name']: (registro.get('payload') or {})
            for registro in self._local_store.list_params(app_name)
        }

    def list_apps(self) -> Dict[str, Any]:
        """
        Lista os apps. ADITIVO: não existia antes, então não quebra nada.

        Em modo remoto consome `GET /parameters/apps/`, que o cliente não
        chamava até agora — a rota está congelada no teste de contrato
        justamente porque passou a ter consumidor.

        Devolve a mesma forma de topo nos dois modos: `{'apps': [...]}`.
        """
        if self._mode == MODO_LOCAL:
            return {'apps': self._local_store.list_apps()}

        url = f'{self._api_base_url}/parameters/apps/'
        res = requests.get(
            url,
            headers=self._auth_headers_optional(),
            timeout=self._timeout,
            verify=self._verify_ssl,
        )
        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao listar apps: {res.text}')
        return res.json()

    def create_app(self, name: str, description: str | None = None):
        if self._mode == MODO_LOCAL:
            registro = self._local_store.upsert_app(name, description)
            logger.info(
                f'[ParamManager: {self._instance_name}] App {name!r} '
                f'criado localmente. Ele só existirá no servidor depois '
                f'de sincronizar.'
            )
            # Mesma forma de topo que o servidor devolve
            # (AppCreatedResponse): quem lê res['app'] não muda de código
            # ao alternar de modo.
            return {
                'message': f'App {name} criado localmente',
                'app': registro,
            }

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

        if self._mode == MODO_LOCAL:
            # Conselho, não veto: quem valida de verdade é o servidor, na
            # sincronização. Isto existe para o erro de digitação não
            # aparecer só no fim de uma sessão inteira de trabalho
            # offline. Avisar e gravar é deliberado — bloquear aqui
            # significaria reimplementar a regra do servidor, que é o
            # erro que o envelope criptográfico já custou caro.
            for aviso in validar_advisory(
                payload[param_name], self._type_catalog()
            ):
                logger.warning(
                    f'[ParamManager: {self._instance_name}] '
                    f'{app_name}.{param_name}: {aviso}. O parâmetro foi '
                    f'gravado localmente; o servidor pode recusá-lo na '
                    f'sincronização.'
                )

            # `dirty` quando já foi sincronizado alguma vez, `draft`
            # quando nunca. A diferença é o que separa "criei agora" de
            # "editei algo que o servidor já conhece", e é ela que a
            # sincronização usa para decidir se precisa conferir
            # divergência antes de empurrar.
            anterior = self._local_store.get_param(app_name, param_name)
            estado = (
                ESTADO_DIRTY
                if anterior and anterior.get('base_hash')
                else ESTADO_DRAFT
            )
            self._local_store.upsert_param(
                app_name, param_name, payload[param_name], state=estado
            )
            # Garante o app no sidecar: upsert_params num app que ainda
            # não existe é caminho comum no desenvolvimento local.
            if not self._local_store.get_app(app_name):
                self._local_store.upsert_app(app_name)
            self.clear_cache(app_name, param_name)
            # Mesma forma de topo que o PUT do servidor devolve.
            return {'app': app_name, 'params': payload}

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

        params = res.json().get('params', {})
        # Aqui o timestamp é o de AGORA, não o do início da requisição:
        # este processo acabou de escrever o valor, então a publicação é
        # autoritativa e precisa vencer o CAS. Trocar por um instante
        # anterior à chamada faria um GET concorrente mais novo derrubar
        # a escrita que o próprio chamador acabou de fazer.
        self._publish_cache(app_name, params, time.time())
        # Invalida cache por parâmetro; ver delete_param para a ordem.
        self.clear_cache(app_name, param_name)
        # Passa snapshot do cache para evitar iteração em estrutura viva.
        self._save_to_local_db(app_name, self._snapshot_cache(app_name))

        return res.json()

    def delete_param(self, app_name: str, param_name: str):
        if self._mode == MODO_LOCAL:
            if not self._local_store.delete_param(app_name, param_name):
                raise LocalStoreError(
                    f'Erro ao deletar parâmetro: {param_name!r} não '
                    f'existe localmente no app {app_name!r}.'
                )
            self.clear_cache(app_name, param_name)
            return {
                'message': f'Parâmetro {param_name} removido localmente'
            }

        url = (
            f'{self._api_base_url}/parameters/apps/'
            f'{app_name}/params/{param_name}'
        )

        res = requests.delete(
            url, headers=self._auth_headers(), timeout=self._timeout
        )

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao deletar parâmetro: {res.text}')

        # Remove do cache local substituindo por dict novo (R2).
        # Não mutar in-place: o dict retornado por referência ao
        # chamador seria afetado.
        with self._state_lock:
            if app_name in self._cache:
                self._cache[app_name] = {
                    k: v
                    for k, v in self._cache[app_name].items()
                    if k != param_name
                }

        # Invalida cache por parâmetro. Deve vir ANTES de
        # _remove_from_local_db para evitar que um get_param concorrente
        # repopule _param_cache a partir de um _cache ainda sujo.
        # E precisa continuar FORA de _remove_from_local_db: aquele
        # método segura self._lock e clear_cache passou a adquirir
        # self._state_lock (CL-2), então chamá-lo de lá criaria a aresta
        # _lock -> _state_lock e fecharia o ciclo ABBA com a aresta
        # oposta. Ambos são threading.Lock, não RLock, de propósito.
        self.clear_cache(app_name, param_name)

        # Remoção explícita: o merge de _save_to_local_db ressuscitaria
        # a chave a partir do registro anterior, e o parâmetro apagado
        # — possivelmente uma credencial revogada — seguiria sendo
        # servido pelo fallback offline.
        self._remove_from_local_db(app_name, param_name)

        return res.json()

    def delete_app(self, app_name: str):
        if self._mode == MODO_LOCAL:
            if not self._local_store.delete_app(app_name):
                raise LocalStoreError(
                    f'Erro ao deletar app: {app_name!r} não existe '
                    f'localmente.'
                )
            self.clear_cache(app_name)
            return {'message': f'App {app_name} removido localmente'}

        url = f'{self._api_base_url}/parameters/apps/{app_name}'

        res = requests.delete(
            url, headers=self._auth_headers(), timeout=self._timeout
        )

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao deletar app: {res.text}')
        self.clear_cache(app_name)

        return res.json()

    # As cinco staticmethods abaixo viraram delegações para
    # `param_manager.crypto` na decomposição. Ficam aqui porque
    # `ParamManager._process_parameter` e afins são chamados por toda a
    # classe e pela suíte; apagá-las seria mudança de superfície, não
    # movimentação de código.
    _is_encrypted_param = staticmethod(_is_encrypted_param)
    _process_parameters = staticmethod(_process_parameters)

    _process_parameter = staticmethod(_process_parameter)
    _extract_value = staticmethod(_extract_value)

    _decrypt_param = staticmethod(_decrypt_param)

    # noqa PLR0911 pelo mesmo motivo de get_param: a cadeia de leitura é
    # uma sequência de saídas antecipadas — modo, cache, breaker, API e
    # os três ramos de erro. Achatá-la em um único return esconderia a
    # estrutura, que é justamente o que se precisa enxergar aqui.
    def get_all_params(self, app_name: str) -> Dict[str, Any]:  # noqa: PLR0911
        logger.info(f'Solicitando todos os parâmetros para o app: {app_name}')

        if self._mode == MODO_LOCAL:
            # Sem cache de propósito: o arquivo é local e quem está
            # desenvolvendo acabou de editá-lo. Cachear aqui só criaria
            # a chance de servir o valor anterior ao próprio usuário.
            # Sem breaker também — não existe rede para falhar.
            return _process_parameters(self._params_locais(app_name))

        if self._is_cache_valid(app_name):
            logger.info(f'Usando cache para o app: {app_name}')
            # Snapshot para processar fora do lock (R1).
            return ParamManager._process_parameters(
                self._snapshot_cache(app_name)
            )
        if self._breaker_active(app_name):
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
        except ParamNotFoundError as e:
            logger.warning(
                f'Parâmetros não encontrados (404) para {app_name}: {str(e)}'
            )
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )
        except (Timeout, ConnectionError) as e:
            logger.error(f'Erro de conexão/timeout: {str(e)}')
            self._arm_breaker(app_name)
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )
        except Exception as e:
            logger.error(f'Erro inesperado ao buscar da API: {str(e)}')
            # Erro HTTP também precisa armar o cooldown, senão a lib
            # martela um servidor que está devolvendo 500.
            self._arm_breaker(app_name)
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

        if self._mode == MODO_LOCAL:
            registro = self._local_store.get_param(app_name, param_name)
            # None e não exceção: o contrato de leitura desta biblioteca
            # é devolver valor ou None, nunca explodir na cara de quem
            # consome. Vale igual no modo local.
            if not registro:
                return None
            return _extract_value(registro.get('payload') or {})

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
            # Snapshot para evitar race ao ler e depois atualizar cache
            # (R1).
            params = self._snapshot_cache(app_name)
            param_value = params.get(param_name)
            if param_value is not None:
                with self._state_lock:
                    self._param_cache[param_cache_key] = param_value
                    self._param_cache_timestamp[param_cache_key] = time.time()
                return ParamManager._extract_value(param_value)
        if self._breaker_active(app_name):
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
        except ParamNotFoundError as e:
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
            self._arm_breaker(app_name)
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
            self._arm_breaker(app_name)
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

        started_at = time.time()
        response = requests.get(
            url,
            timeout=self._timeout,
            verify=self._verify_ssl,
            headers=self._auth_headers_optional(),
        )

        if response.status_code == HTTPStatus.NOT_FOUND:
            raise ParamNotFoundError(
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
                with self._lock:
                    self._db.drop_table(app_name)
                logger.warning(
                    f"Tabela local do app '{app_name}' foi limpa após "
                    f'erro de parsing da API.'
                )
            except Exception as purge_err:
                logger.error(f'Falha ao limpar DB local: {purge_err}')
            return {}

        params = data.get('params', {})

        # CAS: não sobrescreve cache mais novo (R5).
        self._publish_cache(app_name, params, started_at)

        if save_cache:
            # Passa snapshot para evitar iteração em estrutura viva (R1).
            self._save_to_local_db(app_name, self._snapshot_cache(app_name))

        # CAS: só desarma se o breaker foi armado antes desta requisição.
        self._disarm_breaker(app_name, started_at)

        return params

    def _fetch_param_from_api(
        self, app_name: str, param_name: str, save_cache: bool = True
    ) -> Any:
        url = (
            f'{self._api_base_url}/parameters/apps/'
            f'{app_name}/params/{param_name}'
        )
        logger.info(f'Buscando parâmetro específico da API: {url}')
        started_at = time.time()
        response = requests.get(
            url,
            timeout=self._timeout,
            verify=self._verify_ssl,
            headers=self._auth_headers_optional(),
        )
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise ParamNotFoundError(
                f'API retornou status code {response.status_code}'
            )
        if response.status_code != HTTPStatus.OK:
            raise Exception(f'API retornou status code {response.status_code}')
        data = response.json()
        param_value = data.get('param')
        if save_cache:
            param_cache_key = f'{app_name}:{param_name}'
            with self._state_lock:
                self._param_cache[param_cache_key] = param_value
                self._param_cache_timestamp[param_cache_key] = time.time()
                if app_name in self._cache:
                    # Não mutar in-place: substituir por dict novo (R2).
                    self._cache[app_name] = {
                        **self._cache[app_name],
                        param_name: param_value,
                    }
                else:
                    self._cache[app_name] = {param_name: param_value}
            # Passa snapshot para evitar iteração em estrutura viva (R1).
            self._save_to_local_db(app_name, self._snapshot_cache(app_name))
        # CAS: só desarma se o breaker foi armado antes desta requisição.
        self._disarm_breaker(app_name, started_at)

        return param_value

    def _is_cache_valid(self, app_name: str) -> bool:
        with self._state_lock:
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
        with self._state_lock:
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

    def _get_from_local_db(
        self, app_name: str, param_name: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.info(f'Buscando parâmetros localmente para o app: {app_name}')
        try:
            with self._lock:
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
                with self._lock:
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
        # Snapshot dos timestamps para iterar fora do lock (R1).
        cache_ts, param_cache_ts, error_ts = self._snapshot_info()

        # Snapshot dos keys de cache para evitar RuntimeError (R1).
        with self._state_lock:
            cached_apps = list(self._cache.keys())

        info = {
            'apps_cached': cached_apps,
            'cache_timestamps': {},
            'cache_valid': {},
            'params_cached': [],
            'param_cache_timestamps': {},
            'param_cache_valid': {},
            'api_error_timestamps': {},
        }

        for app_name, timestamp in cache_ts.items():
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
        for param_key, timestamp in param_cache_ts.items():
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
        for app_name, timestamp in error_ts.items():
            dt = datetime.fromtimestamp(timestamp)
            cooldown_ends_at = dt + timedelta(seconds=self._effective_cooldown)
            is_cooldown_active = self._breaker_active(app_name)

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
