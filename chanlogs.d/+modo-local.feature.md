Agora é possível desenvolver sem subir o servidor. Passando
`mode='local'` — ou definindo `PARAM_MANAGER_MODE=local` — as mesmas
funções de sempre (`create_app`, `upsert_params`, `delete_param`,
`delete_app`, `get_param`, `get_all_params`) passam a trabalhar num
arquivo local, sem nenhuma chamada de rede. O padrão continua sendo o
servidor, então quem não pedir nada não percebe diferença.

Parâmetros dos tipos `secret`, `user` e `users` não podem ser criados
nesse modo: a cifragem acontece no servidor, e gravá-los localmente
significaria guardar o valor em claro. A tentativa falha com uma
mensagem explicando isso.

Também foi acrescentada a função `list_apps()`, que lista as aplicações
nos dois modos.
