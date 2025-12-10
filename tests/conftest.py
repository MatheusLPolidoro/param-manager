import os
import pytest
from unittest.mock import patch, MagicMock
from param_manager.manager import ParamManager


@pytest.fixture
def setup_param_manager(requests_mock, monkeypatch):
    """
    Fixture principal para inicializar o ParamManager totalmente isolado.
    - Reseta singleton
    - Mocka TinyDB
    - Prepara diretório temporário
    - Injeta mocks de requisição
    """
    # Reset do Singleton
    ParamManager._ParamManager__instance = None

    # Diretório temporário para DB
    test_db_dir = os.path.join(os.path.expanduser('~'), 'param_manager_test')
    os.makedirs(test_db_dir, exist_ok=True)
    test_db_path = os.path.join(test_db_dir, 'test_params_db.json')
    # Simula variáveis do .env
    monkeypatch.setenv("PARAMS_USERNAME", "test_user")
    monkeypatch.setenv("PARAMS_PASSWORD", "secret_pass")
    monkeypatch.setenv("API_PARAMS_URL", "")      # força uso do api_url da fixture
    monkeypatch.setenv("CHAVE_CUSTODIA_APP", "123456") # valor dummy

    # Mock de TinyDB
    with patch('param_manager.manager.TinyDB') as mock_db:
        mock_db_instance = MagicMock()
        mock_db.return_value = mock_db_instance

        mock_table = MagicMock()
        mock_db_instance.table.return_value = mock_table

        # Cria instância
        pm = ParamManager(
            api_url='http://test-api.example.com',
            cache_duration=60,
            timeout=2,
            local_db_path=test_db_dir,
        )

        # Zera tokens
        pm._token = None
        pm._refresh_token = None
        pm._token_expire_at = 0

        yield pm, mock_table, requests_mock

    # cleanup
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    try:
        os.rmdir(test_db_dir)
    except OSError:
        pass
