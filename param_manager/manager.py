import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
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
    e fallback para armazenamento local usando TinyDB quando a API está indisponível.
    """

    # Atributo de classe para armazenar a instância única (padrão Singleton)
    __instance = None

    def __new__(cls, *args, **kwargs):
        """
        Implementa o padrão Singleton, garantindo uma única instância da classe.
        """
        if cls.__instance is None:
            cls.__instance = super(ParamManager, cls).__new__(cls)
            logger.info('Nova instância do ParamManager criada')
        return cls.__instance

    def __init__(
        self, api_url: str = None, cache_duration: int = 3600, timeout: int = 5
    ):
        """
        Inicializa a instância com configurações.

        Args:
            api_url: URL base da API de parâmetros. Se None, usa o valor padrão.
            cache_duration: Duração do cache em segundos (padrão: 1 hora).
            timeout: Tempo limite para requisições à API em segundos.
        """
        # Evita reinicialização se já foi inicializado
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._api_base_url = api_url or 'http://10.111.188.61:8084'
        self._cache_duration = (
            cache_duration  # em segundos (1 hora por padrão)
        )
        self._timeout = timeout  # em segundos

        # Dicionário para armazenar resultados em cache
        self._cache = {}  # formato: {app_name: {params}}

        # Dicionário para armazenar timestamps de cada cache
        self._cache_timestamp = {}  # formato: {app_name: timestamp}

        # Cache específico para parâmetros individuais
        self._param_cache = {}  # formato: {app_name:param_name: param_value}
        self._param_cache_timestamp = {}  # formato: {app_name:param_name: timestamp}

        # Diretório para o banco de dados local
        db_dir = os.path.join(os.path.expanduser('~'), '.param_manager')
        os.makedirs(db_dir, exist_ok=True)

        # Instância do TinyDB para armazenamento local
        self._db_path = os.path.join(db_dir, 'params_db.json')
        self._db = TinyDB(self._db_path)

        self._initialized = True
        logger.info(f'ParamManager inicializado com API: {self._api_base_url}')

    @staticmethod
    def get_instance(
        api_url: str = None, cache_duration: int = 3600, timeout: int = 5
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
            ParamManager(api_url, cache_duration, timeout)
        return ParamManager.__instance

    def get_all_params(self, app_name: str) -> Dict[str, Any]:
        """
        Recupera todos os parâmetros de um app específico.

        Args:
            app_name: Nome do aplicativo.

        Returns:
            Dicionário com todos os parâmetros do app.
        """
        logger.info(f'Solicitando todos os parâmetros para o app: {app_name}')

        # Verifica se há cache válido
        if self._is_cache_valid(app_name):
            logger.info(f'Usando cache para o app: {app_name}')
            return self._cache[app_name]

        # Se não houver cache válido, tenta buscar da API
        try:
            params = self._fetch_from_api(app_name)
            return params
        except Exception as e:
            logger.error(f'Erro ao buscar parâmetros da API: {str(e)}')
            return self._handle_api_error(app_name, None, e)

    def get_param(self, app_name: str, param_name: str) -> Any:
        """
        Recupera um parâmetro específico de um app.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro.

        Returns:
            Valor do parâmetro ou None se não encontrado.
        """
        logger.info(
            f'Solicitando parâmetro {param_name} para o app: {app_name}'
        )

        # Chave para o cache específico do parâmetro
        param_cache_key = f'{app_name}:{param_name}'

        # Verifica se há cache específico válido para o parâmetro
        if self._is_param_cache_valid(app_name, param_name):
            logger.info(
                f'Usando cache específico para o parâmetro: {param_name} do app: {app_name}'
            )
            return self._param_cache[param_cache_key]['value']

        # Se não houver cache específico válido, verifica o cache global do app
        if self._is_cache_valid(app_name):
            logger.info(
                f'Usando cache global do app para o parâmetro: {param_name}'
            )
            params = self._cache[app_name]
            param_value = params.get(param_name)

            # Atualiza o cache específico do parâmetro
            if param_value is not None:
                self._param_cache[param_cache_key] = param_value
                self._param_cache_timestamp[param_cache_key] = time.time()

            return param_value.get('value')

        # Se não houver cache válido, tenta buscar da API
        try:
            # Busca o parâmetro específico da API
            param_value = self._fetch_param_from_api(app_name, param_name)
            if not isinstance(param_value, dict):
                param_value = dict()
            return param_value.get('value')
        except Exception as e:
            logger.error(f'Erro ao buscar parâmetro da API: {str(e)}')

            # Tenta recuperar do banco local
            params = self._handle_api_error(app_name, param_name, e)
            return (
                params.get(param_name, dict()).get('value') if params else None
            )

    def _fetch_from_api(
        self, app_name: str, param_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Faz requisição à API para buscar todos os parâmetros de um app.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro específico (opcional, mantido para compatibilidade).

        Returns:
            Dicionário com os parâmetros.

        Raises:
            Exception: Se ocorrer erro na requisição.
        """
        # Constrói URL apropriada para todos os parâmetros
        url = f'{self._api_base_url}/parameters/apps/{app_name}/params'

        logger.info(f'Buscando todos os parâmetros da API: {url}')

        # Faz requisição HTTP
        response = requests.get(url, timeout=self._timeout, verify=False)

        # Verifica se a requisição foi bem-sucedida
        if response.status_code != 200:
            raise Exception(f'API retornou status code {response.status_code}')

        # Processa resposta
        data = response.json()

        # Extrai parâmetros da resposta
        params = data.get('params', {})

        # Atualiza cache e timestamp
        self._cache[app_name] = params
        self._cache_timestamp[app_name] = time.time()

        # Salva dados localmente
        self._save_to_local_db(app_name, params)

        return params

    def _fetch_param_from_api(self, app_name: str, param_name: str) -> Any:
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
        url = f'{self._api_base_url}/parameters/apps/{app_name}/params/{param_name}'

        logger.info(f'Buscando parâmetro específico da API: {url}')

        # Faz requisição HTTP
        response = requests.get(url, timeout=self._timeout, verify=False)

        # Verifica se a requisição foi bem-sucedida
        if response.status_code != 200:
            raise Exception(f'API retornou status code {response.status_code}')

        # Processa resposta
        data = response.json()

        # Extrai parâmetro da resposta
        param_value = data.get('param')

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

    def _save_to_local_db(self, app_name: str, params: Dict[str, Any]) -> None:
        """
        Salva parâmetros no banco local.

        Args:
            app_name: Nome do aplicativo.
            params: Dicionário com os parâmetros.
        """
        logger.info(f'Salvando parâmetros localmente para o app: {app_name}')

        # Define a tabela para o app
        table = self._db.table(app_name)

        # Limpa a tabela antes de inserir novos dados
        table.truncate()

        # Insere os parâmetros
        table.insert({'timestamp': time.time(), 'params': params})

    def _get_from_local_db(
        self, app_name: str, param_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Recupera dados do banco local.

        Args:
            app_name: Nome do aplicativo.
            param_name: Nome do parâmetro específico (opcional).

        Returns:
            Dicionário com os parâmetros ou vazio se não encontrado.
        """
        logger.info(f'Buscando parâmetros localmente para o app: {app_name}')

        # Define a tabela para o app
        table = self._db.table(app_name)

        # Busca o registro mais recente
        records = table.all()

        if not records:
            logger.warning(
                f'Nenhum registro local encontrado para o app: {app_name}'
            )
            return {}

        # Ordena por timestamp (mais recente primeiro)
        records.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

        # Obtém os parâmetros do registro mais recente
        params = records[0].get('params', {})

        # Filtra por param_name se especificado
        if param_name:
            if param_name in params:
                return {param_name: params[param_name]}
            return {}

        return params

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
        Limpa o cache para um app específico, um parâmetro específico ou para todos os apps.

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

        return info
