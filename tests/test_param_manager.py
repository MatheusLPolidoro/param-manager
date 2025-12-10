from datetime import datetime, timedelta
from http import HTTPStatus
import os
import sys
import time
import pytest
import requests
import param_manager.manager as manager

from requests.exceptions import Timeout, ConnectionError
from unittest.mock import patch, MagicMock
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256

from param_manager.manager import ParamManager 


def test_avoids_reinitialization(monkeypatch, tmp_path):
    """Testa se o __init__ não roda novamente quando _initialized já está True."""
    # Resetar singleton
    ParamManager._ParamManager__instance = None

    # Cria diretório temporário válido
    local_path = tmp_path / "local_db"
    local_path.mkdir()

    # Primeira inicialização
    pm1 = ParamManager(api_url="http://test-api.example.com", local_db_path=str(local_path))
    first_db_path = pm1._db_path

    # Segunda inicialização (não deve reinicializar)
    pm2 = ParamManager(api_url="http://another-api.example.com", local_db_path=str(local_path))
    second_db_path = pm2._db_path

    # Verifica que é a mesma instância
    assert pm1 is pm2

    # Verifica que não reinicializou (atributos não mudaram)
    assert second_db_path == first_db_path
    assert pm2._api_base_url == "http://test-api.example.com"
    assert pm2._initialized is True


def test_detects_pyinstaller_base_dir(monkeypatch):
    ParamManager._ParamManager__instance = None  # reset singleton

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/pyinstaller_dir", raising=False)

    with patch("os.path.exists", return_value=False):
        pm = ParamManager(local_db_path=None)

    assert pm._db_path.startswith("/tmp/pyinstaller_dir")


def test_init_prefers_env_db_path(monkeypatch, tmp_path):
    """Testa se usa env_db_path quando existe e não há local_db_path/base_dir."""
    ParamManager._ParamManager__instance = None

    # Cria diretório temporário válido
    env_path = tmp_path / "env_db"
    env_path.mkdir()

    # Simula variável de ambiente
    monkeypatch.setenv("LOCAL_DB_PATH", str(env_path))

    # Simula que o caminho existe
    monkeypatch.setattr(os.path, "exists", lambda path: str(path) == str(env_path))

    # Mocka find_dotenv para não quebrar
    with patch("param_manager.manager.find_dotenv", return_value=str(tmp_path / ".env")):
        pm = ParamManager()

    # O _db_path deve começar com o env_path
    assert str(pm._db_path).startswith(str(env_path))


def test_init_prefers_env_db_path(monkeypatch, tmp_path):
    """Testa se usa env_db_path quando existe e não há local_db_path/base_dir."""
    # Resetar singleton
    ParamManager._ParamManager__instance = None

    # Cria diretório temporário válido
    env_path = tmp_path / "env_db"
    env_path.mkdir()

    # Simula variável de ambiente
    monkeypatch.setenv("LOCAL_DB_PATH", str(env_path))

    # Simula que o caminho existe
    monkeypatch.setattr(os.path, "exists", lambda path: str(path) == str(env_path))

    # Mocka find_dotenv para não quebrar
    with patch("param_manager.manager.find_dotenv", return_value=str(tmp_path / ".env")):
        pm = ParamManager()

    # O _db_path deve começar com o env_path
    assert str(pm._db_path).startswith(str(env_path))


def test_init_uses_cache_if_valid(monkeypatch, tmp_path):
    ParamManager._ParamManager__instance = None

    cache_path = tmp_path / "cache_db"
    cache_path.mkdir()

    # Simula variável de ambiente
    monkeypatch.setenv("LOCAL_DB_PATH", str(cache_path))
    monkeypatch.setattr(os.path, "exists", lambda path: str(path) == str(cache_path))

    with patch("param_manager.manager.find_dotenv", return_value=str(tmp_path / ".env")):
        pm = ParamManager(api_url="http://test-api.example.com")

    # Verifica se o cache foi inicializado corretamente
    assert str(pm._db_path).startswith(str(cache_path))
    assert pm._api_base_url == "http://test-api.example.com"


def test_uses_cache_if_valid(monkeypatch, caplog, tmp_path):
    """Testa se usa o cache quando válido."""
    ParamManager._ParamManager__instance = None

    pm = ParamManager(api_url="http://test-api.example.com", local_db_path=str(tmp_path))        

    app_name = "test_app"
    fake_params = {
        "param1": {"type": "string", "value": "value1"},
        "param2": {"type": "secret", "value": "supersecret"}
    }

    # Simula cache válido
    pm._cache[app_name] = fake_params
    pm._cache_timestamp[app_name] = time.time()

    # Força _is_cache_valid a retornar True
    monkeypatch.setattr(pm, "_is_cache_valid", lambda name: True)

    caplog.set_level("INFO")

    result = pm.get_all_params(app_name)

    # Verifica se retornou os parâmetros processados
    assert "param1" in result
    assert result["param1"]["value"] == "value1"
    assert result["param2"]["value"] == "supersecret"

    # Verifica se log foi registrado
    assert f"Usando cache para o app: {app_name}" in caplog.text


@pytest.mark.parametrize(
    'mock_response_data', [{'param': {'value': 'test_value'}}]
)
def test_get_param_from_api_with_individual_cache(
    setup_param_manager, mock_response_data
):
    """Testa a recuperação de um parâmetro específico com cache individual."""
    param_manager, *_ = setup_param_manager

    # Configura o mock para requests.get
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Primeira chamada - deve acessar a API
        param1 = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API foi chamada corretamente
        mock_get.assert_called_once_with(
            'http://test-api.example.com/parameters/apps/test_app/params/PARAM1',
            timeout=2,
            verify=False,
        )

        # Verifica se o parâmetro foi retornado corretamente
        assert param1 == 'test_value'

        # Verifica se o cache específico foi atualizado
        assert 'test_app:PARAM1' in param_manager._param_cache
        assert 'test_app:PARAM1' in param_manager._param_cache_timestamp

        # Reseta o mock para a próxima chamada
        mock_get.reset_mock()

        # Segunda chamada - deve usar o cache específico
        param2 = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API não foi chamada novamente
        mock_get.assert_not_called()

        # Verifica se o parâmetro foi retornado corretamente do cache
        assert param2 == 'test_value'


@pytest.mark.parametrize(
    'mock_response_data',
    [
        {
            'params': {
                'PARAM1': {'value': 'value1'},
                'PARAM2': {'value': 'value2'},
            }
        }
    ],
)
def test_get_param_from_global_cache(setup_param_manager, mock_response_data):
    """Testa a recuperação de um parâmetro do cache global quando não há cache específico."""
    param_manager, *_ = setup_param_manager

    # Configura o mock para requests.get para a chamada de todos os parâmetros
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response_all = MagicMock()
        mock_response_all.status_code = 200
        mock_response_all.json.return_value = mock_response_data
        mock_get.return_value = mock_response_all

        # Primeiro, busca todos os parâmetros para preencher o cache global
        params = param_manager.get_all_params('test_app')

        # Verifica se a API foi chamada corretamente
        mock_get.assert_called_once_with(
            'http://test-api.example.com/parameters/apps/test_app/params/',
            timeout=2,
            verify=False,
        )

        # Reseta o mock para a próxima chamada
        mock_get.reset_mock()

        # Agora, busca um parâmetro específico - deve usar o cache global
        param = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API não foi chamada novamente
        mock_get.assert_not_called()

        # Verifica se o parâmetro foi retornado corretamente do cache global
        assert param == 'value1'

        # Agora, busca de todos os parametros - deve usar o cache global
        params = param_manager.get_all_params('test_app')

        # Verifica se o cache específico foi atualizado
        assert 'test_app:PARAM1' in param_manager._param_cache
        assert 'test_app:PARAM1' in param_manager._param_cache_timestamp


@pytest.mark.parametrize('mock_response_data', [{'param': 'test_value'}])
def test_cache_expiration_for_individual_param(
    setup_param_manager, mock_response_data
):
    """Testa a expiração do cache para um parâmetro individual."""
    param_manager, *_ = setup_param_manager

    # Configura o mock para requests.get
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Define uma duração de cache muito curta para o teste
        param_manager._cache_duration = 0.1  # 100ms

        # Primeira chamada - deve acessar a API
        param1 = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API foi chamada
        assert mock_get.call_count == 1

        # Espera o cache expirar
        time.sleep(0.2)

        # Reseta o mock para a próxima chamada
        mock_get.reset_mock()

        # Segunda chamada - deve acessar a API novamente
        param2 = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API foi chamada novamente
        assert mock_get.call_count == 1


@pytest.mark.parametrize('mock_response_data', [{'param': 'test_value'}])
def test_clear_cache_for_individual_param(
    setup_param_manager, mock_response_data
):
    """Testa a limpeza do cache para um parâmetro individual."""
    param_manager, *_ = setup_param_manager

    # Configura o mock para requests.get
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Primeira chamada - deve acessar a API
        param1 = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API foi chamada
        assert mock_get.call_count == 1

        # Limpa o cache específico
        param_manager.clear_cache('test_app', 'PARAM1')

        # Reseta o mock para a próxima chamada
        mock_get.reset_mock()

        # Segunda chamada - deve acessar a API novamente
        param2 = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API foi chamada novamente
        assert mock_get.call_count == 1


@pytest.mark.parametrize('mock_response_data', [{'param': 'test_value'}])
def test_clear_cache_for_app_clears_all_related_params(
    setup_param_manager, mock_response_data
):
    """Testa se a limpeza do cache de um app limpa todos os parâmetros relacionados."""
    param_manager, *_ = setup_param_manager

    # Configura o mock para requests.get
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Busca dois parâmetros diferentes para preencher o cache
        param1 = param_manager.get_param('test_app', 'PARAM1')
        param2 = param_manager.get_param('test_app', 'PARAM2')

        # Verifica se a API foi chamada duas vezes
        assert mock_get.call_count == 2

        # Verifica se os caches específicos foram criados
        assert 'test_app:PARAM1' in param_manager._param_cache
        assert 'test_app:PARAM2' in param_manager._param_cache

        # Limpa o cache do app
        param_manager.clear_cache('test_app')

        # Verifica se os caches específicos foram limpos
        assert 'test_app:PARAM1' not in param_manager._param_cache
        assert 'test_app:PARAM2' not in param_manager._param_cache


def test_api_error_fallback_for_individual_param(setup_param_manager):
    """Testa o fallback para dados locais quando a API falha para um parâmetro individual."""
    param_manager, mock_table, _ = setup_param_manager

    # Configura o mock para requests.get para lançar uma exceção
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException(
            'API indisponível'
        )

        # Configura o mock para retornar dados locais
        mock_table.all.return_value = [
            {
                'timestamp': time.time(),
                'params': {'PARAM1': {'value': 'local_value'}},
            }
        ]

        # Chama o método para buscar um parâmetro específico
        param = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se a API foi chamada
        mock_get.assert_called_once()

        # Verifica se os dados locais foram buscados
        mock_table.all.assert_called_once()

        # Verifica se o parâmetro local foi retornado
        assert param == 'local_value'


def test_api_error_fallback_for_all_params(setup_param_manager):
    """Testa o fallback para dados locais quando a API falha para um parâmetro individual."""
    param_manager, mock_table, _ = setup_param_manager

    # Configura o mock para requests.get para lançar uma exceção
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException(
            'API indisponível'
        )

        result = {'PARAM1': {'value': 'value1'}, 'PARAM2': {'value': 'value2'}}
        # Configura o mock para retornar dados locais
        mock_table.all.return_value = [
            {
                'timestamp': time.time(),
                'params': result,
            }
        ]

        # Chama o método para buscar um parâmetro específico
        params = param_manager.get_all_params('test_app')

        # Verifica se a API foi chamada
        mock_get.assert_called_once()

        # Verifica se os dados locais foram buscados
        mock_table.all.assert_called_once()

        # Verifica se o parâmetro local foi retornado
        assert params == result


@pytest.mark.parametrize(
    'mock_response_data', [{'param': {'value': 'test_value'}}]
)
def test_api_error_status_code(setup_param_manager, mock_response_data):
    """Testa se o a chamada da API retorna algo diferente de 200"""
    param_manager, *_ = setup_param_manager

    # Define uma duração de cache muito curta para o teste
    param_manager._cache_duration = 0  # 100ms

    # Configura o mock para requests.get
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Busca um parâmetro para preencher o cache
        param = param_manager.get_param('test_app', 'PARAM1')

        # Verifica se o parâmetro local foi retornado
        assert param == 'test_value'

        mock_response.status_code = 500

        # Busca um parâmetro para preencher o cache
        param = param_manager.get_param('test_app', 'PARAM1')

        assert param == None


@pytest.mark.parametrize(
    'mock_response_data', [{'param': {'value': 'test_value'}}]
)
def test_get_cache_info_includes_param_cache(
    setup_param_manager, mock_response_data
):
    """Testa se o método get_cache_info inclui informações sobre o cache de parâmetros individuais."""
    param_manager, *_ = setup_param_manager

    # Configura o mock para requests.get
    with patch('param_manager.manager.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Busca um parâmetro para preencher o cache
        param = param_manager.get_param('test_app', 'PARAM1')

        # Obtém informações do cache
        cache_info = param_manager.get_cache_info()

        # Verifica se as informações sobre o cache de parâmetros estão presentes
        assert 'params_cached' in cache_info
        assert 'param_cache_timestamps' in cache_info
        assert 'param_cache_valid' in cache_info

        # Verifica se o parâmetro específico está nas informações
        assert 'test_app:PARAM1' in cache_info['params_cached']
        assert 'test_app:PARAM1' in cache_info['param_cache_timestamps']
        assert 'test_app:PARAM1' in cache_info['param_cache_valid']


def test_get_all_params_secret_success(setup_param_manager, monkeypatch):
    """Testa se get_all_params descriptografa corretamente parâmetros secretos."""
    param_manager, *_ = setup_param_manager

    # Define variável de ambiente necessária
    monkeypatch.setenv("CHAVE_CUSTODIA_APP", "segredo_teste")

    # Gera dados criptografados válidos
    salt = os.urandom(16)
    chave_custodia = PBKDF2("segredo_teste".encode(), salt, dkLen=32, count=100_000, hmac_hash_module=SHA256)

    chave_mestra = os.urandom(32)
    cipher_cm = AES.new(chave_custodia, AES.MODE_GCM)
    cm_data, cm_tag = cipher_cm.encrypt_and_digest(chave_mestra)

    senha_original = b"senha_super_secreta"
    cipher_pw = AES.new(chave_mestra, AES.MODE_GCM)
    pw_data, pw_tag = cipher_pw.encrypt_and_digest(senha_original)

    params = {
        "PARAM_SECRET": {
            "type": "secret",
            "value": {
                "salt": salt.hex(),
                "master_key": {
                    "iv": cipher_cm.nonce.hex(),
                    "tag": cm_tag.hex(),
                    "data": cm_data.hex(),
                },
                "crypto_data": {
                    "iv": cipher_pw.nonce.hex(),
                    "tag": pw_tag.hex(),
                    "data": pw_data.hex(),
                },
            },
        }
    }

    # Mock para _fetch_from_api retornar nossos params
    param_manager._fetch_from_api = lambda app_name: params

    result = param_manager.get_all_params("test_app")

    assert result["PARAM_SECRET"]["value"] == senha_original.decode()


def test_get_all_params_secret_missing_env(setup_param_manager, monkeypatch):
    """Retorna None se CHAVE_CUSTODIA_APP não estiver definida."""
    param_manager, *_ = setup_param_manager
    monkeypatch.delenv("CHAVE_CUSTODIA_APP", raising=False)

    params = {
        "PARAM_SECRET": {
            "type": "secret",
            "value": {
                "salt": "00",
                "master_key": {"iv": "00", "tag": "00", "data": "00"},
                "crypto_data": {"iv": "00", "tag": "00", "data": "00"},
            },
        }
    }

    param_manager._fetch_from_api = lambda app_name: params
    result = param_manager.get_all_params("test_app")

    assert result["PARAM_SECRET"]["value"] is None


def test_get_all_params_secret_invalid_data(setup_param_manager, monkeypatch):
    """Retorna None se os dados criptografados forem inválidos."""
    param_manager, *_ = setup_param_manager
    monkeypatch.setenv("CHAVE_CUSTODIA_APP", "segredo_teste")

    params = {
        "PARAM_SECRET": {
            "type": "secret",
            "value": {
                "salt": "zzzz",  # inválido
                "master_key": {"iv": "00", "tag": "00", "data": "00"},
                "crypto_data": {"iv": "00", "tag": "00", "data": "00"},
            },
        }
    }

    param_manager._fetch_from_api = lambda app_name: params
    result = param_manager.get_all_params("test_app")

    assert result["PARAM_SECRET"]["value"] is None


def test_get_all_params_secret_missing_fields(setup_param_manager, monkeypatch):
    """Retorna None se o dicionário do parâmetro secreto não tiver todos os campos obrigatórios."""
    param_manager, *_ = setup_param_manager
    monkeypatch.setenv("CHAVE_CUSTODIA_APP", "segredo_teste")

    # Valor incompleto: falta 'crypto_data'
    params = {
        "PARAM_SECRET": {
            "type": "secret",
            "value": {
                "salt": "00",
                "master_key": {"iv": "00", "tag": "00", "data": "00"},
                # 'crypto_data' ausente
            },
        }
    }

    # Mock da API para retornar esse valor
    param_manager._fetch_from_api = lambda app_name: params

    result = param_manager.get_all_params("test_app")

    # Como faltam campos, o valor deve ser None
    assert result["PARAM_SECRET"]["value"] is None


def test_get_all_params_uses_local_on_api_error_cached(setup_param_manager):
    """Testa se get_all_params usa dados locais quando há erro de API anterior (cooldown)."""
    param_manager, mock_table, requests = setup_param_manager

    # Força o estado de erro de API anterior
    param_manager._is_api_error_cached = lambda app_name: True

    # Mock para retornar dados locais
    local_params = {
        "PARAM1": {"value": "local_value1"},
        "PARAM2": {"value": "local_value2"},
    }
    param_manager._get_from_local_db = lambda app_name: local_params

    # Chama get_all_params
    result = param_manager.get_all_params("test_app")

    # Verifica se os dados locais foram retornados
    assert result == local_params
    assert result["PARAM1"]["value"] == "local_value1"
    assert result["PARAM2"]["value"] == "local_value2"


def test_get_all_params_timeout_or_connection_error(setup_param_manager):
    """Testa se get_all_params trata Timeout/ConnectionError corretamente."""
    param_manager, *_ = setup_param_manager

    # Força _fetch_from_api a lançar Timeout
    def fake_fetch(app_name):
        raise Timeout("Simulando timeout")
    param_manager._fetch_from_api = fake_fetch

    # Mock de _handle_api_error para retornar dados locais simulados
    local_params = {"PARAM1": {"value": "local_value"}}
    param_manager._handle_api_error = lambda app_name, *_: local_params

    # Chama get_all_params
    result = param_manager.get_all_params("test_app")

    # Verifica se o resultado veio do handle_api_error
    assert result == local_params
    assert result["PARAM1"]["value"] == "local_value"

    # Verifica se o timestamp de erro foi registrado
    assert "test_app" in param_manager._api_error_timestamp
    assert isinstance(param_manager._api_error_timestamp["test_app"], float)


def test_get_all_params_timeout_or_connection_error(setup_param_manager):
    """Testa se get_all_params trata Timeout/ConnectionError corretamente."""
    param_manager, *_ = setup_param_manager

    # Força _fetch_from_api a lançar Timeout
    def fake_fetch(app_name):
        raise Timeout("Simulando timeout")
    param_manager._fetch_from_api = fake_fetch

    # Mock de _handle_api_error para retornar dados locais simulados
    local_params = {"PARAM1": {"value": "local_value"}}
    param_manager._handle_api_error = lambda app_name, *_: local_params

    # Chama get_all_params
    result = param_manager.get_all_params("test_app")

    # Verifica se o resultado veio do handle_api_error
    assert result == local_params
    assert result["PARAM1"]["value"] == "local_value"

    # Verifica se o timestamp de erro foi registrado
    assert "test_app" in param_manager._api_error_timestamp
    assert isinstance(param_manager._api_error_timestamp["test_app"], float)


def test_get_all_params_connection_error(setup_param_manager):
    """Testa se get_all_params trata ConnectionError corretamente."""
    param_manager, *_ = setup_param_manager

    # Força _fetch_from_api a lançar ConnectionError
    def fake_fetch(app_name):
        raise ConnectionError("Simulando erro de conexão")
    param_manager._fetch_from_api = fake_fetch

    # Mock de _handle_api_error para retornar dados locais simulados
    local_params = {"PARAM2": {"value": "local_value2"}}
    param_manager._handle_api_error = lambda app_name, *_: local_params

    result = param_manager.get_all_params("test_app")

    assert result == local_params
    assert result["PARAM2"]["value"] == "local_value2"
    assert "test_app" in param_manager._api_error_timestamp


import os
import pytest
import time
from requests.exceptions import Timeout, ConnectionError
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256


def test_get_param_from_specific_cache(setup_param_manager):
    """Testa retorno do cache específico."""
    param_manager, *_ = setup_param_manager
    param_manager._param_cache["test_app:PARAM1"] = {"value": "cached_value"}
    param_manager._param_cache_timestamp["test_app:PARAM1"] = time.time()

    # Força cache válido
    param_manager._is_param_cache_valid = lambda app, param: True

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "cached_value"


def test_get_param_from_global_cache(setup_param_manager):
    """Testa retorno do cache global quando não há cache específico."""
    param_manager, *_ = setup_param_manager
    param_manager._cache["test_app"] = {"PARAM1": {"value": "global_value"}}
    param_manager._is_cache_valid = lambda app: True

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "global_value"
    assert "test_app:PARAM1" in param_manager._param_cache


def test_get_param_api_error_cached(setup_param_manager):
    """Testa retorno de dados locais quando há erro de API anterior."""
    param_manager, *_ = setup_param_manager
    param_manager._is_api_error_cached = lambda app: True
    param_manager._get_from_local_db = lambda app, param: {"PARAM1": {"value": "local_value"}}

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "local_value"


def test_get_param_fetch_from_api_success(setup_param_manager):
    """Testa busca de parâmetro diretamente da API."""
    param_manager, *_ = setup_param_manager
    param_manager._is_param_cache_valid = lambda app, param: False
    param_manager._is_cache_valid = lambda app: False
    param_manager._is_api_error_cached = lambda app: False
    param_manager._fetch_param_from_api = lambda app, param: {"value": "api_value"}

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "api_value"


def test_get_param_fetch_from_api_timeout(setup_param_manager):
    """Testa fallback quando ocorre Timeout na API."""
    param_manager, *_ = setup_param_manager
    param_manager._fetch_param_from_api = lambda app, param: (_ for _ in ()).throw(Timeout("timeout"))
    param_manager._handle_api_error = lambda app, param, e: {"PARAM1": {"value": "fallback_value"}}

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "fallback_value"
    assert "test_app" in param_manager._api_error_timestamp


def test_get_param_fetch_from_api_connection_error(setup_param_manager):
    """Testa fallback quando ocorre ConnectionError na API."""
    param_manager, *_ = setup_param_manager
    param_manager._fetch_param_from_api = lambda app, param: (_ for _ in ()).throw(ConnectionError("conn error"))
    param_manager._handle_api_error = lambda app, param, e: {"PARAM1": {"value": "fallback_value"}}

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "fallback_value"
    assert "test_app" in param_manager._api_error_timestamp


def test_get_param_fetch_from_api_unexpected_error(setup_param_manager):
    """Testa fallback quando ocorre erro inesperado na API."""
    param_manager, *_ = setup_param_manager
    param_manager._fetch_param_from_api = lambda app, param: (_ for _ in ()).throw(RuntimeError("unexpected"))
    param_manager._handle_api_error = lambda app, param, e: {"PARAM1": {"value": "fallback_value"}}

    result = param_manager.get_param("test_app", "PARAM1")
    assert result == "fallback_value"


def test_get_param_password_decryption_success(setup_param_manager, monkeypatch):
    """Testa descriptografia de parâmetro do tipo password."""
    param_manager, *_ = setup_param_manager
    monkeypatch.setenv("CHAVE_CUSTODIA_APP", "segredo_teste")

    # Gera dados criptografados válidos
    salt = os.urandom(16)
    chave_custodia = PBKDF2("segredo_teste".encode(), salt, dkLen=32, count=100_000, hmac_hash_module=SHA256)

    chave_mestra = os.urandom(32)
    cipher_cm = AES.new(chave_custodia, AES.MODE_GCM)
    cm_data, cm_tag = cipher_cm.encrypt_and_digest(chave_mestra)

    senha_original = b"senha_super_secreta"
    cipher_pw = AES.new(chave_mestra, AES.MODE_GCM)
    pw_data, pw_tag = cipher_pw.encrypt_and_digest(senha_original)

    param_manager._fetch_param_from_api = lambda app, param: {
        "value": {
            "salt": salt.hex(),
            "master_key": {
                "iv": cipher_cm.nonce.hex(),
                "tag": cm_tag.hex(),
                "data": cm_data.hex(),
            },
            "crypto_data": {
                "iv": cipher_pw.nonce.hex(),
                "tag": pw_tag.hex(),
                "data": pw_data.hex(),
            },
        },
        "type": "secret"
    }

    result = param_manager.get_param("test_app", "PARAM_SECRET")
    assert result == senha_original.decode()


def test_get_param_password_decryption_missing_fields(setup_param_manager, monkeypatch):
    """Retorna o valor bruto se faltar campos obrigatórios no parâmetro password."""
    param_manager, *_ = setup_param_manager
    monkeypatch.setenv("CHAVE_CUSTODIA_APP", "segredo_teste")

    param_manager._fetch_param_from_api = lambda app, param: {
        "value": {"salt": "00"}  # faltam master_key e crypto_data
    }

    result = param_manager.get_param("test_app", "PARAM_SECRET")
    assert result == {"salt": "00"}  # retorna o valor bruto


def test_get_param_password_decryption_missing_env(setup_param_manager, monkeypatch):
    """Retorna o valor bruto se variável de ambiente não estiver definida."""
    param_manager, *_ = setup_param_manager
    monkeypatch.delenv("CHAVE_CUSTODIA_APP", raising=False)

    param_manager._fetch_param_from_api = lambda app, param: {
        "value": {
            "salt": "00",
            "master_key": {"iv": "00", "tag": "00", "data": "00"},
            "crypto_data": {"iv": "00", "tag": "00", "data": "00"},
        }
    }

    result = param_manager.get_param("test_app", "PARAM_SECRET")
    # Esperado: retorna o valor bruto, já que não conseguiu descriptografar
    assert result == {
        "salt": "00",
        "master_key": {"iv": "00", "tag": "00", "data": "00"},
        "crypto_data": {"iv": "00", "tag": "00", "data": "00"},
    }


def test_fetch_from_api_success(setup_param_manager):
    """Testa fluxo feliz: API retorna 200 e dados válidos."""
    param_manager, *_ = setup_param_manager

    mock_response_data = {
        "params": {
            "PARAM1": {"value": "value1"},
            "PARAM2": {"value": "value2"},
        }
    }

    with patch("param_manager.manager.requests.get") as mock_get, \
         patch.object(param_manager, "_save_to_local_db") as mock_save:

        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        result = param_manager._fetch_from_api("test_app")

        # Verifica retorno
        assert result == mock_response_data["params"]

        # Verifica cache atualizado
        assert param_manager._cache["test_app"] == mock_response_data["params"]
        assert "test_app" in param_manager._cache_timestamp

        # Verifica que salvou no banco local
        mock_save.assert_called_once_with("test_app", mock_response_data["params"])

        # Verifica que timestamp de erro foi limpo
        param_manager._api_error_timestamp["test_app"] = time.time()
        result = param_manager._fetch_from_api("test_app")
        assert "test_app" not in param_manager._api_error_timestamp


def test_fetch_from_api_status_code_error(setup_param_manager):
    """Testa quando API retorna status diferente de 200."""
    param_manager, *_ = setup_param_manager

    with patch("param_manager.manager.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        mock_get.return_value = mock_response

        with pytest.raises(Exception) as excinfo:
            param_manager._fetch_from_api("test_app")

        assert "API retornou status code" in str(excinfo.value)


def test_fetch_from_api_empty_params(setup_param_manager):
    """Testa quando API retorna resposta sem 'params'."""
    param_manager, *_ = setup_param_manager

    mock_response_data = {"other_key": "no_params_here"}

    with patch("param_manager.manager.requests.get") as mock_get, \
         patch.object(param_manager, "_save_to_local_db") as mock_save:

        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        result = param_manager._fetch_from_api("test_app")

        # Deve retornar dict vazio
        assert result == {}

        # Cache atualizado com dict vazio
        assert param_manager._cache["test_app"] == {}
        assert "test_app" in param_manager._cache_timestamp

        # Salvo no banco local
        mock_save.assert_called_once_with("test_app", {})


def test_fetch_from_api_json_error(setup_param_manager):
    """Testa quando response.json lança exceção."""
    param_manager, *_ = setup_param_manager

    with patch("param_manager.manager.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response

        with pytest.raises(ValueError):
            param_manager._fetch_from_api("test_app")


def test_fetch_param_from_api_clears_error_timestamp(setup_param_manager):
    """Testa se _fetch_param_from_api remove o timestamp de erro após sucesso da API."""
    param_manager, *_ = setup_param_manager

    # Simula que o app já está em erro
    param_manager._api_error_timestamp["test_app"] = 123456789.0

    mock_response_data = {"param": {"value": "param_value"}}

    with patch("param_manager.manager.requests.get") as mock_get, \
         patch.object(param_manager, "_save_to_local_db") as mock_save:

        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        result = param_manager._fetch_param_from_api("test_app", "PARAM1")

        # Verifica retorno correto
        assert result == {"value": "param_value"}

        # Verifica cache específico atualizado
        assert param_manager._param_cache["test_app:PARAM1"] == {"value": "param_value"}
        assert "test_app:PARAM1" in param_manager._param_cache_timestamp

        # Verifica cache global atualizado
        assert param_manager._cache["test_app"]["PARAM1"] == {"value": "param_value"}

        # Verifica que salvou no banco local
        mock_save.assert_called_once_with("test_app", {"PARAM1": {"value": "param_value"}})

        # Verifica que o timestamp foi removido
        assert "test_app" not in param_manager._api_error_timestamp


def test_is_cache_valid_true(setup_param_manager):
    """Retorna True quando o cache é recente (dentro do cache_duration)."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 60  # 60 segundos

    # Simula cache criado agora
    param_manager._cache["test_app"] = {"PARAM1": {"value": "value1"}}
    param_manager._cache_timestamp["test_app"] = time.time()

    assert param_manager._is_cache_valid("test_app") is True


def test_is_cache_valid_false_expired(setup_param_manager):
    """Retorna False quando o cache está expirado (fora do cache_duration)."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 1  # 1 segundo

    # Simula cache criado há 5 segundos
    param_manager._cache["test_app"] = {"PARAM1": {"value": "value1"}}
    param_manager._cache_timestamp["test_app"] = time.time() - 5

    assert param_manager._is_cache_valid("test_app") is False


def test_is_api_error_cached_app_not_in_timestamp(setup_param_manager):
    """Retorna False se o app não estiver em _api_error_timestamp."""
    param_manager, *_ = setup_param_manager

    # Nenhum erro registrado
    assert param_manager._is_api_error_cached("test_app") is False


def test_is_api_error_cached_true_recent_error(setup_param_manager):
    """Retorna True se o erro for recente (dentro do cache_duration)."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 60  # 60 segundos

    # Simula erro ocorrido agora
    param_manager._api_error_timestamp["test_app"] = time.time()

    assert param_manager._is_api_error_cached("test_app") is True


def test_is_api_error_cached_false_expired_error(setup_param_manager):
    """Retorna False se o erro for antigo (fora do cache_duration)."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 1  # 1 segundo

    # Simula erro ocorrido há 5 segundos
    param_manager._api_error_timestamp["test_app"] = time.time() - 5

    assert param_manager._is_api_error_cached("test_app") is False


def test_get_from_local_db_no_records(setup_param_manager, caplog):
    """Retorna {} e gera warning quando não há registros locais para o app."""
    param_manager, mock_table, requests = setup_param_manager

    # Simula que não há registros no banco local
    mock_table.all.return_value = []

    # Ativa captura de logs
    caplog.set_level("WARNING")

    result = param_manager._get_from_local_db("test_app")

    # Verifica retorno vazio
    assert result == {}

    # Verifica se log de warning foi emitido
    assert any(
        "Nenhum registro local encontrado para o app: test_app" in message
        for message in caplog.messages
    )


def test_api_error_timestamp_removed_on_success(setup_param_manager):
    """Testa se o timestamp de erro é removido após sucesso da API."""
    param_manager, *_ = setup_param_manager

    # Simula que o app já está marcado com erro
    param_manager._api_error_timestamp["test_app"] = 123456789.0

    mock_response_data = {"params": {"PARAM1": {"value": "value1"}}}

    with patch("param_manager.manager.requests.get") as mock_get, \
         patch.object(param_manager, "_save_to_local_db") as mock_save:

        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        # Chama _fetch_from_api para simular sucesso
        result = param_manager._fetch_from_api("test_app")

        # Verifica retorno correto
        assert result == {"PARAM1": {"value": "value1"}}

        # Verifica que o timestamp foi removido
        assert "test_app" not in param_manager._api_error_timestamp

        # Verifica que salvou no banco local
        mock_save.assert_called_once_with("test_app", {"PARAM1": {"value": "value1"}})


def test_clear_cache_app_level_removes_api_error_timestamp(setup_param_manager):
    """Testa se clear_cache remove o timestamp de erro quando limpa cache de um app específico."""
    param_manager, *_ = setup_param_manager

    # Simula dados de cache e erro para o app
    param_manager._cache["test_app"] = {"PARAM1": {"value": "value1"}}
    param_manager._cache_timestamp["test_app"] = 123456789.0
    param_manager._api_error_timestamp["test_app"] = 987654321.0

    # Chama clear_cache apenas com app_name
    param_manager.clear_cache(app_name="test_app")

    # Verifica que cache e timestamp foram removidos
    assert "test_app" not in param_manager._cache
    assert "test_app" not in param_manager._cache_timestamp
    assert "test_app" not in param_manager._api_error_timestamp


def test_clear_cache_all_clears_everything(setup_param_manager, caplog):
    """Testa se clear_cache limpa todos os caches quando nenhum parâmetro é fornecido."""
    param_manager, *_ = setup_param_manager

    # Simula dados em todos os caches
    param_manager._cache = {"app1": {"PARAM1": {"value": "value1"}}}
    param_manager._cache_timestamp = {"app1": 123456789.0}
    param_manager._param_cache = {"app1:PARAM1": {"value": "value1"}}
    param_manager._param_cache_timestamp = {"app1:PARAM1": 123456789.0}
    param_manager._api_error_timestamp = {"app1": 987654321.0}

    caplog.set_level("INFO")

    # Chama clear_cache sem argumentos
    param_manager.clear_cache()

    # Verifica que todos os caches foram resetados
    assert param_manager._cache == {}
    assert param_manager._cache_timestamp == {}
    assert param_manager._param_cache == {}
    assert param_manager._param_cache_timestamp == {}
    assert param_manager._api_error_timestamp == {}

    # Verifica se log foi emitido
    assert any("Cache limpo para todos os apps e parâmetros" in msg for msg in caplog.messages)


def test_cache_info_with_valid_cache(setup_param_manager):
    """Testa se cache_info retorna timestamps corretos quando cache é válido."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 60  # 60 segundos

    # Simula cache criado agora
    now = time.time()
    param_manager._cache["test_app"] = {"PARAM1": {"value": "value1"}}
    param_manager._cache_timestamp["test_app"] = now

    # Chama método que gera info (supondo que seja get_cache_info)
    info = param_manager.get_cache_info()

    # Verifica estrutura
    assert "test_app" in info["cache_timestamps"]
    ts_info = info["cache_timestamps"]["test_app"]

    # cached_at e expires_at devem ser ISO strings
    dt = datetime.fromtimestamp(now)
    expires_at = dt + timedelta(seconds=param_manager._cache_duration)
    assert ts_info["cached_at"] == dt.isoformat()
    assert ts_info["expires_at"] == expires_at.isoformat()

    # seconds_remaining deve ser > 0
    assert ts_info["seconds_remaining"] > 0

    # cache_valid deve ser True
    assert info["cache_valid"]["test_app"] is True


def test_cache_info_with_expired_cache(setup_param_manager):
    """Testa se cache_info retorna seconds_remaining=0 quando cache está expirado."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 1  # 1 segundo

    # Simula cache criado há 5 segundos (expirado)
    past = time.time() - 5
    param_manager._cache["test_app"] = {"PARAM1": {"value": "value1"}}
    param_manager._cache_timestamp["test_app"] = past

    info = param_manager.get_cache_info()

    ts_info = info["cache_timestamps"]["test_app"]

    # seconds_remaining deve ser 0
    assert ts_info["seconds_remaining"] == 0

    # cache_valid deve ser False
    assert info["cache_valid"]["test_app"] is False


def test_cache_info_with_recent_api_error(setup_param_manager):
    """Retorna info correta quando há erro de API recente (cooldown ativo)."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 60  # 60 segundos

    # Simula erro ocorrido agora
    now = time.time()
    param_manager._api_error_timestamp["test_app"] = now

    info = param_manager.get_cache_info()

    # Verifica estrutura
    assert "test_app" in info["api_error_timestamps"]
    ts_info = info["api_error_timestamps"]["test_app"]

    dt = datetime.fromtimestamp(now)
    cooldown_ends_at = dt + timedelta(seconds=param_manager._cache_duration)

    # error_at e cooldown_ends_at devem ser ISO strings
    assert ts_info["error_at"] == dt.isoformat()
    assert ts_info["cooldown_ends_at"] == cooldown_ends_at.isoformat()

    # cooldown_remaining_seconds deve ser > 0
    assert ts_info["cooldown_remaining_seconds"] > 0


def test_cache_info_with_expired_api_error(setup_param_manager):
    """Retorna info correta quando erro de API está expirado (cooldown inativo)."""
    param_manager, *_ = setup_param_manager
    param_manager._cache_duration = 1  # 1 segundo

    # Simula erro ocorrido há 5 segundos (expirado)
    past = time.time() - 5
    param_manager._api_error_timestamp["test_app"] = past

    info = param_manager.get_cache_info()

    ts_info = info["api_error_timestamps"]["test_app"]

    dt = datetime.fromtimestamp(past)
    cooldown_ends_at = dt + timedelta(seconds=param_manager._cache_duration)

    # error_at e cooldown_ends_at devem ser ISO strings
    assert ts_info["error_at"] == dt.isoformat()
    assert ts_info["cooldown_ends_at"] == cooldown_ends_at.isoformat()

    # cooldown_remaining_seconds deve ser 0 porque cooldown expirou
    assert ts_info["cooldown_remaining_seconds"] == 0
