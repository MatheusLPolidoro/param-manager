# Configuração

## A ordem de precedência

Para quase tudo, a ordem é:

```
argumento do construtor  >  {INSTANCE_NAME}_VARIAVEL  >  VARIAVEL
```

O prefixo é o `instance_name` **em maiúsculas**. Com
`instance_name='producao'`, a variável específica é `PRODUCAO_CACHE_DURATION` e
a genérica é `CACHE_DURATION`.

!!! danger "Duas variáveis invertem essa ordem"

    `TIMEOUT` e `CACHE_DURATION` **não** seguem a regra: hoje a variável de
    ambiente vence o argumento do construtor. Passar `timeout=30` no código não
    tem efeito se `TIMEOUT` existir no ambiente.

    É dívida conhecida e está registrada. Consertar significa mudar os defaults
    de `get_instance` para `None`, o que altera uma assinatura pública — por
    isso está segurado para uma versão maior.

## As variáveis

### Conexão

| Variável | Alternativas | Default |
|---|---|---|
| `API_{INSTANCE}_URL` | `API_PARAMS_URL`, `API_URL` | `''` |
| `TIMEOUT` | — | `5` |
| `VERIFY_SSL` | `{INSTANCE}_VERIFY_SSL` | `False` |

A URL é resolvida nesta ordem: argumento `api_url`, depois
`API_{INSTANCE}_URL`, depois `API_PARAMS_URL`, depois `API_URL`. **Não há
prefixo de instância nas duas últimas.**

### Credenciais

| Variável | Default |
|---|---|
| `{INSTANCE}_PARAMS_USERNAME` ou `PARAMS_USERNAME` | *(nenhum)* |
| `{INSTANCE}_PARAMS_PASSWORD` ou `PARAMS_PASSWORD` | *(nenhum)* |

!!! warning "O tutorial antigo erra o nome"

    A documentação antiga fala em `PARAM_MANAGER_USERNAME` e
    `PARAM_MANAGER_PASSWORD`. Os nomes corretos são `PARAMS_USERNAME` e
    `PARAMS_PASSWORD`.

### Cache e resiliência

| Variável | Alternativa | Default |
|---|---|---|
| `CACHE_DURATION` | `{INSTANCE}_CACHE_DURATION` | `300` no construtor, **`3600`** em `get_instance` |
| `API_ERROR_COOLDOWN` | `{INSTANCE}_API_ERROR_COOLDOWN` | Cai para `cache_duration` |

!!! note "O default de cache depende de como você constrói"

    `ParamManager(...)` usa **300 s**. `ParamManager.get_instance(...)` usa
    **3600 s**. As duas formas são públicas e os dois valores estão no código.
    Se a validade do cache importa para você, **passe o valor explicitamente**.

### Armazenamento local

| Variável | Default |
|---|---|
| `LOCAL_DB_PATH` | Diretório do `.env`, ou o diretório corrente |

O arquivo final fica em:

```
<base>/param_manager/<instance_name>/params_<instance_name>.json
```

A ordem de resolução da base é: argumento `local_db_path`, depois o diretório do
PyInstaller quando congelado, depois `LOCAL_DB_PATH`, depois o diretório do
`.env`, e por último o diretório de trabalho.

!!! warning "O caminho mudou na 0.4.0"

    A documentação antiga fala em `param_manager/params_db.json`, sem o nível da
    instância. Desde a 0.4.0 é um diretório por instância.

### Criptografia

| Variável | Alternativa |
|---|---|
| `CHAVE_CUSTODIA_APP` | `APP_CUSTODY_KEY` |

Tem que casar com o `APP_CUSTODY_KEY` do servidor. Se não casar, a decifragem
falha — e ela falha **em silêncio**: o cliente registra um erro no log e devolve
`None`. O formato está descrito em [Envelope criptográfico](https://matheuslpolidoro.github.io/docs-param-manager/latest/seguranca/envelope/), no site do produto.

### Cache legado

| Variável | Efeito |
|---|---|
| `PARAM_MANAGER_PURGE_PLAINTEXT_CACHE` | Purga, na inicialização, cache local antigo gravado em claro |

É opt-in. Ligue uma vez ao migrar de uma versão que gravava valor sensível sem
cifrar.

## `verify_ssl` tem escopo parcial

Este é o ponto mais fácil de diagnosticar errado da biblioteca inteira.

A flag governa **apenas os dois GETs de leitura**. Autenticação e escrita
verificam a cadeia TLS sempre, e isso é deliberado: o `POST /auth/token` carrega
usuário e senha, e rebaixar o TLS dele seria pior do que a assimetria.

!!! danger "O sintoma em ambiente com certificado interno"

    **A leitura funciona e a autenticação falha por SSL.** Parece configuração
    pela metade; é o comportamento projetado. A saída correta é instalar a
    cadeia interna no sistema, não procurar uma flag que desligue a verificação
    do login.

O default de `verify_ssl` é `False`, porque os ambientes que consomem a
biblioteca usam certificado interno. Quem tem cadeia confiável pode — e deve —
passar `verify_ssl=True`.

Os valores aceitos na variável de ambiente são `1`, `true`, `yes` e `on`,
sem diferenciar maiúsculas. Qualquer outra coisa é falso.

## Exemplo de `.env`

```bash
API_PARAMS_URL=https://parametros.exemplo.com
PARAMS_USERNAME=servico-relatorios
PARAMS_PASSWORD=...
CACHE_DURATION=600
API_ERROR_COOLDOWN=60
VERIFY_SSL=true
CHAVE_CUSTODIA_APP=...

# Uma segunda instância, com sobrescritas próprias
API_HOMOLOG_URL=https://parametros-homolog.exemplo.com
HOMOLOG_CACHE_DURATION=30
```
