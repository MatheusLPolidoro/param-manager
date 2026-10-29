# Biblioteca ParamManager

## Descrição
Biblioteca Python para consumir a API de parâmetros Fast Param Manager. Oferece cache em memória, armazenamento local com TinyDB, fallback automático quando a API está indisponível, um modo de desenvolvimento sem servidor e, como extra, um aplicativo de desktop.

Documentação completa: <https://matheuslpolidoro.github.io/param-manager/>

## Funcionalidades

- **Instâncias nomeadas**: cada `instance_name` tem uma única instância por processo, com cache, configuração e arquivo local próprios. Sem nome, todas as chamadas compartilham a instância `default`.
- **Cache**: guarda os resultados em memória para reduzir chamadas à API — 300 s com `ParamManager(...)`, 3600 s com `ParamManager.get_instance(...)`, ou o que você passar em `cache_duration`.
- **Armazenamento local**: usa TinyDB para persistir os parâmetros lidos.
- **Fallback automático**: usa os dados locais quando a API está indisponível, e espera um intervalo configurável (`api_error_cooldown`) antes de tentar de novo.
- **Escrita**: cria e atualiza aplicações e parâmetros (`create_app`, `upsert_params`, `delete_param`, `delete_app`).
- **Modo local**: `mode='local'` trabalha num arquivo, sem rede, e sincroniza depois com `sync_plan()` / `sync_apply()`.
- **Front desktop**: `pip install "param-manager[front]"` traz o aplicativo `param-manager-front` (Python 3.11 a 3.13).

## Fluxo de resolução

![Fluxo do cliente](https://raw.githubusercontent.com/MatheusLPolidoro/param-manager/master/docs/assets/fluxo-cliente.png)

## Instalação

```bash
pip install param-manager
```

Com o aplicativo de desktop:

```bash
pip install "param-manager[front]"
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
param_manager = ParamManager.get_instance(
    api_url="http://minha-api.exemplo.com",
    cache_duration=1800,     # 30 minutos
    timeout=10,              # 10 segundos
    api_error_cooldown=60,   # espera após uma falha da API
    verify_ssl=True,         # verificação TLS nas leituras
)
```

Todas essas opções também podem vir de variáveis de ambiente ou do `.env`, com ou sem o prefixo do nome da instância. A lista completa e a ordem de precedência estão em [Configuração](https://matheuslpolidoro.github.io/param-manager/latest/configuracao/).

## Comportamento de Fallback

Quando a API está indisponível, a biblioteca automaticamente:
1. Tenta acessar a API
2. Em caso de falha, busca dados do armazenamento local
3. Retorna os dados mais recentes disponíveis localmente
4. Durante o intervalo de espera, segue usando os dados locais sem chamar a API

## Dependências

- Python 3.10+ (o extra `front` exige 3.11 a 3.13)
- requests
- tinydb
- pycryptodome
- python-dotenv
