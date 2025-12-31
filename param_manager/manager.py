import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, Dict, Optional

import requests
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from dotenv import find_dotenv, load_dotenv
from requests.exceptions import ConnectionError, Timeout
from tinydb import TinyDB

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('ParamManager')


class ParamManager:
    """
    Gerenciador de parâmetros que implementa o padrão Singleton.

    Esta classe permite recuperar parâmetros de uma API, com sistema de cache
    e fallback para armazenamento local usando TinyDB
    quando a API está indisponível.
    """

    # Atributo de classe para armazenar a instância única (padrão Singleton)
    __instance = None

    def __new__(cls, *args, **kwargs):
        """
        Implementa o padrão Singleton, garantindo
        uma única instância da classe.
        """
        if cls.__instance is None:
            cls.__instance = super(ParamManager, cls).__new__(cls)
            logger.info('Nova instância do ParamManager criada')
        return cls.__instance

    def __init__(  # noqa: PLR0913 PLR0917
        self,
        api_url: str | None = None,
        cache_duration: int = 3600,
        timeout: int = 5,
        local_db_path: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        # Procura e carrega .env do diretório correto
        # Detecta se está rodando como executável PyInstaller
        if getattr(sys, 'frozen', False):
            base_dir = (
                sys._MEIPASS
            )  # Diretório temporário onde PyInstaller extrai os arquivos
            dotenv_path = os.path.join(base_dir, '.env')
        else:
            base_dir = None
            dotenv_path = find_dotenv()

        load_dotenv(dotenv_path=dotenv_path)

        self._cache_duration = int(os.getenv('CACHE_DURATION', cache_duration))
        self._username = os.getenv('PARAMS_USERNAME', username)
        self._password = os.getenv('PARAMS_PASSWORD', password)

        # Evita reinicialização
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._lock = threading.Lock()
        self._token = None
        self._refresh_token = None
        self._token_expire_at = 0
        self._timeout = int(os.getenv('TIMEOUT', timeout))
        self._api_base_url = (
            api_url
            or os.getenv('API_PARAMS_URL', '')
            or os.getenv('API_URL', '')
        )
        env_db_path = os.getenv('LOCAL_DB_PATH')
        if local_db_path and os.path.exists(local_db_path):
            current_dir = local_db_path
        elif base_dir:
            current_dir = base_dir
        elif env_db_path and os.path.exists(env_db_path):
            current_dir = env_db_path
        else:
            current_dir = (
                os.path.dirname(dotenv_path)
                if dotenv_path
                else os.path.dirname(os.path.abspath(__file__))
            )

        db_dir = os.path.join(current_dir, 'param_manager')
        os.makedirs(db_dir, exist_ok=True)

        self._db_path = os.path.join(db_dir, 'params_db.json')
        self._db = TinyDB(self._db_path)

        self._cache = {}
        self._cache_timestamp = {}
        self._param_cache = {}
        self._param_cache_timestamp = {}
        self._api_error_timestamp = {}

        self._initialized = True
        logger.info(f'ParamManager inicializado com API: {self._api_base_url}')

    @staticmethod
    def get_instance(
        api_url: str = None,
        cache_duration: int = 3600,
        timeout: int = 5,
        *args,
        **kwargs,
    ) -> 'ParamManager':
        """
        Método estático para obter a instância única.

        Args:
            api_url: URL base da API de parâmetros.
            cache_duration: Duração do cache em segundos.
            timeout: Tempo limite para requisições à API em segundos.

        Returns:
            A instância única de ParamManager.
        """
        if ParamManager.__instance is None:
            ParamManager(api_url, cache_duration, timeout, *args, **kwargs)
        return ParamManager.__instance

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

        res = requests.post(url, data=data)

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

        res = requests.post(url, data=data)

        if res.status_code != HTTPStatus.OK:
            return self._auth_get_token()

        auth_data = res.json()
        self._token = auth_data.get('access_token')
        self._refresh_token = auth_data.get('refresh_token')

        self._token_expire_at = time.time() + 29 * 60

        return self._token

    def _get_valid_token(self):
        if not self._token:
            return self._auth_get_token()

        if time.time() >= self._token_expire_at:
            return self._auth_refresh_token()

        return self._token

    def _auth_headers(self):
        token = self._get_valid_token()
        return {'Authorization': f'Bearer {token}'}

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
        user_editable: bool | None = False,
        min_length: int | None = None,
        max_length: int | None = None,
        min_value: int | float | None = None,
        max_value: int | float | None = None,
        referenced_params: list[str] | None = None,
    ):
        """
        Upsert de parâmetro com payload limpo e automático,
        respeitando 100% o schema do OpenAPI.
        """

        # Campos obrigatórios
        payload = {
            param_name: {
                'value': value,
                'type': param_type,
            }
        }

        # Campos opcionais → adicionados dinamicamente
        optional_fields = {
            'description': description,
            'user_editable': user_editable,
            'min_length': min_length,
            'max_length': max_length,
            'min_value': min_value,
            'max_value': max_value,
            'referenced_params': referenced_params,
        }

        # adiciona apenas valores que não são None
        payload[param_name].update({
            key: val for key, val in optional_fields.items() if val is not None
        })

        # Endpoint
        url = f'{self._api_base_url}/parameters/apps/{app_name}/params/'

        res = requests.put(
            url,
            json=payload,
            headers=self._auth_headers(),
            timeout=self._timeout,
        )

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao fazer upsert de parâmetros: {res.text}')

        # Cache
        self._cache[app_name] = res.json().get('params', {})
        self._cache_timestamp[app_name] = time.time()
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

        self._save_to_local_db(app_name, self._cache.get(app_name, {}))

        return res.json()

    def delete_app(self, app_name: str):
        url = f'{self._api_base_url}/parameters/apps/{app_name}'

        res = requests.delete(
            url, headers=self._auth_headers(), timeout=self._timeout
        )

        if res.status_code != HTTPStatus.OK:
            raise Exception(f'Erro ao deletar app: {res.text}')

        # limpa caches locais
        self.clear_cache(app_name)

        return res.json()

    @staticmethod
    def _process_parameters(params: dict) -> dict:
        for _, p in params.items():
            ParamManager._process_parameter(p)
        return params

    @staticmethod
    def _process_parameter(params: dict) -> dict | None:
        if params.get('type') == 'secret':
            raw = params.get('value')
            if isinstance(raw, dict):
                params['value'] = ParamManager._descriptografar_param(raw)
        elif params.get('type') == 'users':
            raw: list[dict] = params['value']
            if isinstance(raw, list):
                for item in raw:
                    item['password'] = ParamManager._descriptografar_param(
                        item['password']
                    )
        elif params.get('type') == 'user':
            raw: dict = params['value']
            if isinstance(raw, dict):
                if 'password' in raw.keys():
                    raw['password'] = ParamManager._descriptografar_param(
                        raw['password']
                    )
        return params

    @staticmethod
    def _extract_value(param_value: dict) -> Any:
        if param_value.get('type') in {'secret', 'users', 'user'}:
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

        # Verifica cache
        if self._is_cache_valid(app_name):
            logger.info(f'Usando cache para o app: {app_name}')
            return ParamManager._process_parameters(self._cache[app_name])

        # Verifica erro de API anterior
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
        except (Timeout, ConnectionError) as e:
            logger.error(f'Erro de conexão/timeout: {str(e)}')
            self._api_error_timestamp[app_name] = time.time()
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )
        except Exception as e:
            logger.error(f'Erro inesperado ao buscar da API: {str(e)}')
            return ParamManager._process_parameters(
                self._handle_api_error(app_name, None, e)
            )

    def get_param(
        self, app_name: str, param_name: str, save_cache: bool = True
    ) -> Any:
        """
        Recupera um parâmetro específico de um app.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro.

        Returns:
            Valor do parâmetro descriptografado, se for tipo password, ou None.
        """

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

        # Verifica cache global
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

        # Verifica erro anterior
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

        # Tenta buscar da API
        try:
            param_value = self._fetch_param_from_api(
                app_name, param_name, save_cache
            )
            if not isinstance(param_value, dict):
                param_value = dict()
            return ParamManager._extract_value(param_value)
        except (Timeout, ConnectionError) as e:
            logger.error(
                f'Erro de conexão/timeout ao buscar parâmetro da API: {str(e)}'
            )
            self._api_error_timestamp[app_name] = time.time()
            params = self._handle_api_error(app_name, param_name, e)
            return (
                ParamManager._extract_value(params.get(param_name, dict()))
                if params
                else None
            )
        except Exception as e:
            logger.error(
                f'Erro inesperado ao buscar parâmetro da API: {str(e)}'
            )
            params = self._handle_api_error(app_name, param_name, e)
            return (
                ParamManager._extract_value(params.get(param_name, dict()))
                if params
                else None
            )

    def _fetch_from_api(
        self,
        app_name: str,
        param_name: Optional[str] = None,
        save_cache: bool = True,
    ) -> Dict[str, Any]:
        url = f'{self._api_base_url}/parameters/apps/{app_name}/params/'
        logger.info(f'Buscando todos os parâmetros da API: {url}')

        response = requests.get(url, timeout=self._timeout, verify=False)

        if response.status_code != HTTPStatus.OK:
            raise Exception(f'API retornou status code {response.status_code}')

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            logger.error(
                f'Erro de JSON na resposta da API para {app_name}: {e}'
            )
            # limpa DB local
            try:
                self._db.purge_tables()
                logger.warning(
                    'DB local foi limpo após erro de parsing da API.'
                )
            except Exception as purge_err:
                logger.error(f'Falha ao limpar DB local: {purge_err}')
            # retorna vazio para não travar
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
        """
        Faz requisição à API para buscar um parâmetro específico.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro específico.

        Returns:
            Valor do parâmetro ou None se não encontrado.

        Raises:
            Exception: Se ocorrer erro na requisição.
        """
        # Constrói URL apropriada para o parâmetro específico
        url = (
            f'{self._api_base_url}/parameters/apps/'
            f'{app_name}/params/{param_name}'
        )

        logger.info(f'Buscando parâmetro específico da API: {url}')

        # Faz requisição HTTP
        response = requests.get(url, timeout=self._timeout, verify=False)

        # Verifica se a requisição foi bem-sucedida
        if response.status_code != HTTPStatus.OK:
            raise Exception(f'API retornou status code {response.status_code}')

        # Processa resposta
        data = response.json()

        # Extrai parâmetro da resposta
        param_value = data.get('param')

        if save_cache:
            # Chave para o cache específico do parâmetro
            param_cache_key = f'{app_name}:{param_name}'

            # Atualiza o cache específico do parâmetro
            self._param_cache[param_cache_key] = param_value
            self._param_cache_timestamp[param_cache_key] = time.time()

            # Também atualiza o cache global se existir
            if app_name in self._cache:
                self._cache[app_name][param_name] = param_value
                self._cache_timestamp[app_name] = time.time()
            else:
                self._cache[app_name] = {param_name: param_value}

            # Salva dados localmente
            self._save_to_local_db(app_name, self._cache[app_name])

        # Limpa o timestamp de erro da API se a requisição foi bem-sucedida
        if app_name in self._api_error_timestamp:
            del self._api_error_timestamp[app_name]

        return param_value

    def _is_cache_valid(self, app_name: str) -> bool:
        """
        Verifica se o cache global para um app é válido.

        Args:
            app_name: Nome do aplicativo.

        Returns:
            True se o cache for válido, False caso contrário.
        """
        # Verifica se existe cache para o app
        if (
            app_name not in self._cache
            or app_name not in self._cache_timestamp
        ):
            return False

        # Verifica se o timestamp é recente (menos de cache_duration segundos)
        current_time = time.time()
        cache_time = self._cache_timestamp[app_name]

        return (current_time - cache_time) < self._cache_duration

    def _is_param_cache_valid(self, app_name: str, param_name: str) -> bool:
        """
        Verifica se o cache específico para um parâmetro é válido.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro.

        Returns:
            True se o cache for válido, False caso contrário.
        """
        # Chave para o cache específico do parâmetro
        param_cache_key = f'{app_name}:{param_name}'

        # Verifica se existe cache específico para o parâmetro
        if (
            param_cache_key not in self._param_cache
            or param_cache_key not in self._param_cache_timestamp
        ):
            return False

        # Verifica se o timestamp é recente (menos de cache_duration segundos)
        current_time = time.time()
        cache_time = self._param_cache_timestamp[param_cache_key]

        return (current_time - cache_time) < self._cache_duration

    def _is_api_error_cached(self, app_name: str) -> bool:
        """
        Verifica se houve um erro de API recente para o app
        e se o cooldown ainda está ativo.

        Args:
            app_name: Nome do aplicativo.

        Returns:
            True se o erro de API estiver em cooldown, False caso contrário.
        """
        if app_name not in self._api_error_timestamp:
            return False

        current_time = time.time()
        error_time = self._api_error_timestamp[app_name]

        # O erro é considerado "em cache" (cooldown) se o
        # tempo desde o erro for menor que a duração do cache
        return (current_time - error_time) < self._cache_duration

    def _save_to_local_db(self, app_name: str, params: Dict[str, Any]) -> None:
        """
        Atualiza parâmetros no banco local sem apagar os existentes.
        """
        logger.info(f'Salvando parâmetros localmente para o app: {app_name}')

        with self._lock:
            table = self._db.table(app_name)

            # Recupera o registro atual (se existir)
            existing = table.get(doc_id=1)  # assumindo um único doc por app

            if existing:
                # Mescla os parâmetros antigos com os novos
                merged_params = {**existing['params'], **params}
                table.update(
                    {'timestamp': time.time(), 'params': merged_params},
                    doc_ids=[1],
                )
            else:
                # Se não existe ainda, insere
                table.insert({'timestamp': time.time(), 'params': params})

    def _get_from_local_db(
        self, app_name: str, param_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Recupera dados do banco local. Se ocorrer erro de leitura,
        limpa o DB e tenta nova requisição à API.
        """
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
            # Limpa completamente o banco local
            try:
                self._db.purge_tables()
                logger.warning('DB local corrompido foi limpo.')
            except Exception as purge_err:
                logger.error(f'Falha ao limpar DB local: {purge_err}')
            # Tenta nova requisição à API
            try:
                return self._fetch_from_api(app_name, param_name)
            except Exception as api_err:
                logger.error(f'Nova requisição à API também falhou: {api_err}')
                return {}

    def _handle_api_error(
        self, app_name: str, param_name: Optional[str], error: Exception
    ) -> Dict[str, Any]:
        """
        Trata erros de API.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro específico (opcional).
            error: Exceção ocorrida.

        Returns:
            Dados locais se disponíveis ou dicionário vazio.
        """
        logger.error(f'Erro ao acessar API para {app_name}: {str(error)}')
        logger.info(f'Tentando usar dados locais para {app_name}')

        # Busca dados locais
        return self._get_from_local_db(app_name, param_name)

    def clear_cache(
        self, app_name: Optional[str] = None, param_name: Optional[str] = None
    ) -> None:
        """
        Limpa o cache para um app específico, um parâmetro
        específico ou para todos os apps.

        Args:
            app_name: Nome do aplicativo (opcional).
            param_name: Nome do parâmetro (opcional).
        """
        if app_name and param_name:
            # Limpa o cache específico do parâmetro
            param_cache_key = f'{app_name}:{param_name}'
            if param_cache_key in self._param_cache:
                del self._param_cache[param_cache_key]
            if param_cache_key in self._param_cache_timestamp:
                del self._param_cache_timestamp[param_cache_key]
            logger.info(
                f'Cache limpo para o parâmetro {param_name} do app: {app_name}'
            )
        elif app_name:
            # Limpa o cache do app
            if app_name in self._cache:
                del self._cache[app_name]
            if app_name in self._cache_timestamp:
                del self._cache_timestamp[app_name]
            if app_name in self._api_error_timestamp:
                del self._api_error_timestamp[app_name]

            # Limpa também todos os caches específicos relacionados ao app
            param_cache_keys = [
                k
                for k in self._param_cache.keys()
                if k.startswith(f'{app_name}:')
            ]
            for key in param_cache_keys:
                if key in self._param_cache:
                    del self._param_cache[key]
                if key in self._param_cache_timestamp:
                    del self._param_cache_timestamp[key]

            logger.info(f'Cache limpo para o app: {app_name}')
        else:
            # Limpa todos os caches
            self._cache = {}
            self._cache_timestamp = {}
            self._param_cache = {}
            self._param_cache_timestamp = {}
            self._api_error_timestamp = {}
            logger.info('Cache limpo para todos os apps e parâmetros')

    def get_cache_info(self) -> Dict[str, Any]:
        """
        Retorna informações sobre o cache atual.

        Returns:
            Dicionário com informações do cache.
        """
        info = {
            'apps_cached': list(self._cache.keys()),
            'cache_timestamps': {},
            'cache_valid': {},
            'params_cached': [],
            'param_cache_timestamps': {},
            'param_cache_valid': {},
            'api_error_timestamps': {},
        }

        # Informações sobre o cache global
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

        # Informações sobre o cache específico de parâmetros
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

        # Informações sobre os timestamps de erro da API
        for app_name, timestamp in self._api_error_timestamp.items():
            dt = datetime.fromtimestamp(timestamp)
            cooldown_ends_at = dt + timedelta(seconds=self._cache_duration)
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
