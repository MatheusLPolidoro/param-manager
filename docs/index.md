# Biblioteca ParamManager

## Descrição
Biblioteca Python orientada a objetos que implementa o padrão Singleton para interagir com a API de parâmetros. A biblioteca oferece funcionalidades de cache, armazenamento local com TinyDB e fallback automático em caso de indisponibilidade da API.

## Funcionalidades

- **Padrão Singleton**: Garante que exista apenas uma instância da classe de acesso à API
- **Cache**: Armazena resultados em memória por até 1 hora para reduzir chamadas à API
- **Armazenamento Local**: Usa TinyDB para persistir dados localmente
- **Fallback Automático**: Utiliza dados locais quando a API está indisponível
- **Recuperação de Parâmetros**: Permite buscar todos os parâmetros de um app ou um parâmetro específico

## Instalação

```bash
pip install param-manager
```

## Uso Básico

```python
from param_manager import ParamManager

# Obter a instância do gerenciador
param_manager = ParamManager.get_instance()

# Recuperar todos os parâmetros de um app
params = param_manager.get_all_params('nome_do_app')

# Recuperar um parâmetro específico
param = param_manager.get_param('nome_do_app', 'NOME_PARAMETRO')

# Limpar o cache para um app específico
param_manager.clear_cache('nome_do_app')

# Obter informações sobre o cache atual
cache_info = param_manager.get_cache_info()
```

## Configuração Avançada

```python
# Configurar com URL de API personalizada, duração de cache e timeout
param_manager = ParamManager.get_instance(
    api_url="http://minha-api.exemplo.com",
    cache_duration=1800,  # 30 minutos
    timeout=10  # 10 segundos
)
```

## Comportamento de Fallback

Quando a API está indisponível, a biblioteca automaticamente:
1. Tenta acessar a API
2. Em caso de falha, busca dados do armazenamento local
3. Retorna os dados mais recentes disponíveis localmente

## Estrutura de Arquivos

- `param_manager.py`: Implementação principal da biblioteca
- `test_param_manager.py`: Testes unitários para validar o funcionamento
- `requirements.txt`: Dependências necessárias
- `requirements-dev.txt`: Dependências de desenvolvimento necessárias

## :open_file_folder: Layout do Projeto

```
├───param_manager
│   │   manager.py
│   └───__init__.py
```

## Dependências

- Python 3.6+
- requests
- tinydb



## :clock2: Changelogs

:: towncrier-draft Unreleased changes

--8<-- "CHANGELOG.md"


## :jigsaw: Diagrama de Classes

``` mermaid
classDiagram
    class ParamManager {
        - __instance: Optional~ParamManager~
        - _api_base_url: str
        - _cache_duration: int
        - _timeout: int
        - _cache: Dict
        - _cache_timestamp: Dict
        - _param_cache: Dict
        - _param_cache_timestamp: Dict
        - _db_path: str
        - _db: TinyDB
        - _initialized: bool
        + __new__(cls, *args, **kwargs): ParamManager
        + __init__(self, api_url: Optional~str~ = None, cache_duration: int = 3600, timeout: int = 5): None
        + get_instance(api_url: Optional~str~ = None, cache_duration: int = 3600, timeout: int = 5): ParamManager
        + get_all_params(self, app_name: str): Dict
        + get_param(self, app_name: str, param_name: str): Any
        - _fetch_from_api(self, app_name: str, param_name: Optional~str~ = None): Dict
        - _fetch_param_from_api(self, app_name: str, param_name: str): Any
        - _is_cache_valid(self, app_name: str): bool
        - _is_param_cache_valid(self, app_name: str, param_name: str): bool
        - _save_to_local_db(self, app_name: str, params: Dict): None
        - _get_from_local_db(self, app_name: str, param_name: Optional~str~ = None): Dict
        - _handle_api_error(self, app_name: str, param_name: Optional~str~, error: Exception): Dict
        + clear_cache(self, app_name: Optional~str~ = None, param_name: Optional~str~ = None): None
        + get_cache_info(self): Dict
    }
```
