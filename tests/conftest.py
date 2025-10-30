import os
import pytest
from param_manager.manager import ParamManager
from unittest.mock import patch, MagicMock


@pytest.fixture
def setup_param_manager():
    """Fixture para configurar o ambiente de teste para o ParamManager."""
    # Limpa a instância singleton entre os testes
    ParamManager._ParamManager__instance = None

    # Cria um diretório temporário para o banco de dados de teste
    test_db_dir = os.path.join(os.path.expanduser('~'), 'param_manager_test')
    os.makedirs(test_db_dir, exist_ok=True)
    test_db_path = os.path.join(test_db_dir, 'test_params_db.json')

    # Mock para o TinyDB
    with patch('param_manager.manager.TinyDB') as mock_db:
        mock_db_instance = MagicMock()
        mock_db.return_value = mock_db_instance

        # Mock para a tabela do TinyDB
        mock_table = MagicMock()
        mock_db_instance.table.return_value = mock_table

        # Cria a instância do ParamManager com URL de API de teste
        param_manager = ParamManager.get_instance(
            api_url='http://test-api.example.com',
            cache_duration=60,  # 1 minuto para facilitar os testes
            timeout=2,
        )

        # Retorna os objetos necessários para os testes
        yield param_manager, mock_table

    # Limpeza após o teste
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    # Remove o diretório de teste se estiver vazio
    try:
        os.rmdir(test_db_dir)
    except OSError:
        pass
