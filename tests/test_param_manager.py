import time
import pytest
from unittest.mock import patch, MagicMock

import requests


@pytest.mark.parametrize(
    'mock_response_data', [{'param': {'value': 'test_value'}}]
)
def test_get_param_from_api_with_individual_cache(
    setup_param_manager, mock_response_data
):
    """Testa a recuperação de um parâmetro específico com cache individual."""
    param_manager, _ = setup_param_manager

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
    param_manager, _ = setup_param_manager

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
    param_manager, _ = setup_param_manager

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
    param_manager, _ = setup_param_manager

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
    param_manager, _ = setup_param_manager

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
    param_manager, mock_table = setup_param_manager

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
    param_manager, mock_table = setup_param_manager

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
    param_manager, _ = setup_param_manager

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
    param_manager, _ = setup_param_manager

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
