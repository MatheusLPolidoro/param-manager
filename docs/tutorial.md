## Uso Básico
- Crie um arquivo main.py com:

```python
from param_manager import ParamManager

# Obter a instância do gerenciador
param_manager = ParamManager.get_instance()

# Recuperar todos os parâmetros de um app
params = param_manager.get_all_params('nome_do_app')

# Recuperar um parâmetro específico
param = param_manager.get_param('nome_do_app', 'nome_parametro')

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
