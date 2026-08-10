# Modo local — desenvolver sem o servidor

Até aqui o `ParamManager` só sabia trabalhar contra a API: qualquer
leitura ou escrita precisava do servidor no ar. O **modo local** remove
essa dependência para o dia a dia de desenvolvimento — você cria a
aplicação, escreve os parâmetros e lê tudo de um arquivo na sua máquina,
sem nenhuma chamada de rede. Quando quiser, sincroniza com o servidor.

!!! info "O padrão não mudou"
    O modo padrão continua sendo `remote`, com exatamente o mesmo
    comportamento de sempre. Se você não pedir o modo local, nada muda
    para o seu código.

## Ligando o modo local

Pelo construtor:

```python
from param_manager import ParamManager

params = ParamManager.get_instance(
    instance_name='dev',
    mode='local',
)
```

Ou por variável de ambiente, sem tocar no código:

```bash
# vale para todas as instâncias
PARAM_MANAGER_MODE=local

# ou só para a instância chamada "dev"
DEV_PARAM_MANAGER_MODE=local
```

A precedência é a mesma do resto da biblioteca: **argumento do
construtor > variável prefixada pela instância > variável global**.

Para saber em que modo você está:

```python
params.mode  # 'local' ou 'remote'
```

## Trabalhando offline

As funções são as mesmas dos dois modos — o que muda é o destino:

```python
params.create_app('financeiro', 'Contas a pagar')

params.upsert_params(
    'financeiro', 'porta',
    value=8080,
    param_type='int',
)

params.get_param('financeiro', 'porta')      # 8080
params.get_all_params('financeiro')
params.list_apps()

params.delete_param('financeiro', 'porta')
params.delete_app('financeiro')
```

O rascunho fica num arquivo próprio, ao lado do cache:

```
<base>/param_manager/<instancia>/local_<instancia>.json
```

!!! warning "Ele é separado do cache de propósito"
    A biblioteca limpa o cache automaticamente quando a API responde
    algo ilegível. Se o rascunho morasse no mesmo arquivo, essa limpeza
    apagaria o que você ainda não sincronizou — por causa de uma falha
    que não tem nada a ver com ele.

## Parâmetros protegidos não são criados offline

Os tipos `secret`, `user` e `users` **não podem ser criados no modo
local**. A cifragem desses valores acontece no servidor, e gravá-los
localmente significaria guardar o conteúdo em claro no seu disco.

```python
params.upsert_params('financeiro', 'senha', value='x', param_type='secret')
# LocalStoreError: ... só pode ser criado com o servidor ...
```

Ler um parâmetro protegido que **já foi sincronizado** continua
funcionando normalmente: o valor cifrado está no cache e a biblioteca
sabe decifrá-lo.

## Aviso antecipado de valor inválido

Ao gravar, a biblioteca compara o valor com o catálogo de tipos do
servidor e avisa no log quando ele provavelmente será recusado:

```python
params.upsert_params('financeiro', 'nome', value='x' * 40, param_type='string')
# WARNING ... comprimento 40 passa do máximo 30; informe max_length no upsert
```

**O aviso não impede a gravação.** Quem valida de verdade é o servidor,
na sincronização — o objetivo aqui é que o erro apareça na hora, e não
no fim de uma sessão inteira de trabalho.

O limite padrão de 30 caracteres é do servidor, e vale quando o pedido
não informa outro. Para elevá-lo, mande o limite junto:

```python
params.upsert_params(
    'financeiro', 'nome',
    value='x' * 40,
    param_type='string',
    max_length=100,
)
```

Para manter o catálogo atualizado — útil antes de ficar sem servidor por
um tempo:

```python
params.refresh_type_catalog()
```

## Enviando para o servidor

A sincronização tem **duas etapas**, e isso é proposital: você vê o que
vai acontecer antes de acontecer.

```python
plano = params.sync_plan()

plano['apps_to_create']   # apps que ainda não existem no servidor
plano['summary']          # {'create': 2, 'update': 1, 'conflict': 1}

for item in plano['params']:
    print(item['app'], item['name'], item['action'], item['reason'])
```

`sync_plan()` **não grava nada** — nem local, nem no servidor. Quando
estiver satisfeito:

```python
resultado = params.sync_apply(plano)

resultado['apps_created']       # apps criados no servidor
resultado['synced']             # parâmetros enviados com sucesso
resultado['rejected']           # recusados, com a mensagem do servidor
resultado['forbidden']          # sem permissão
resultado['skipped_conflicts']  # deixados de fora
```

### Conflitos nunca são resolvidos sozinhos

Quando o mesmo parâmetro mudou dos dois lados, ele é marcado como
conflito, **fica de fora** da aplicação e é apresentado com os dois
valores para você decidir:

```python
for item in plano['params']:
    if item['action'] == 'conflict':
        print(item['name'], 'local:', item['local'], 'servidor:', item['remote'])
```

Para forçar o envio de um conflito, mude a ação do item para `'update'`
antes de aplicar — assim a decisão fica explícita:

```python
item['action'] = 'update'
params.sync_apply(plano)
```

### O que acontece quando o servidor recusa

Cada caso é tratado de forma diferente, porque significam coisas
diferentes:

| Situação | O que acontece |
|---|---|
| Valor inválido | O parâmetro **continua guardado localmente**, com a mensagem exata do servidor, e os demais continuam sendo enviados |
| Sem permissão | O parâmetro segue pendente, para ser tentado de novo quando a credencial for corrigida |
| App não existe | O app é criado no servidor antes dos parâmetros |

A sincronização é retomável: se ela for interrompida no meio, a execução
seguinte continua de onde parou.

## Voltando para o servidor

Depois de sincronizar, construa uma instância nova em modo remoto:

```python
params.sync_apply(params.sync_plan())

producao = ParamManager.get_instance(
    instance_name='producao',
    api_url='https://params.exemplo.com',
    mode='remote',
)
```

!!! note "Por que uma instância nova"
    Uma instância já criada não é reconfigurada — essa proteção existe
    para evitar que parte do seu código passe a enxergar uma
    configuração diferente da outra parte no meio da execução.

## Interface gráfica

Para aplicações com interface, o módulo `param_manager.api` oferece as
mesmas operações em funções que devolvem sempre um dicionário com `ok`,
em vez de lançar exceções:

```python
from param_manager import api

api.configure(instance_name='front', mode='local', api_url='...')

resposta = api.get_all_params('financeiro', instance_name='front')
if resposta['ok']:
    print(resposta['params'])
else:
    print(resposta['error'])
```

!!! warning "As funções bloqueiam"
    Elas fazem requisições, leitura de disco e decifragem. Chame-as fora
    do laço de eventos da interface, sob pena de a janela congelar.
