# Gerenciador de parametros

Biblioteca para gerenciamento de parâmetros.


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

## :open_file_folder: Layout do Projeto

```
├───param_manager
│   │   manager.py
│   └───__init__.py
```