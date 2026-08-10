"""
Planejamento da sincronização — puro, sem rede e sem lock.

A orquestração (HTTP, ordem, gravação) mora no `manager`. Aqui fica só a
decisão: dado o que existe localmente e o que o servidor devolveu, o que
fazer com cada parâmetro. Separar assim é o que torna a regra de conflito
testável sem servidor e sem arquivo.

## A unidade é o parâmetro, não o app

`PUT /parameters/apps/{app}/params/` recebe um dicionário e o servidor faz
**merge** — mandar um subconjunto é escrita legal e não destrutiva.
Sincronizar por app obrigaria a reenviar parâmetros dos quais o cliente
pode ter cópia velha, o que é um gerador de lost update.

## Como a divergência é detectada

O cliente **não enxerga** `params_version`: o servidor o declara
`exclude=True` e ele não aparece em resposta nenhuma. O que existe é o
documento completo do parâmetro no GET. Então `base_hash` guarda a
impressão do **documento do servidor** na última sincronização
bem-sucedida, e a comparação é contra o documento atual:

- servidor não tem o parâmetro  → `create`
- hash atual == `base_hash`     → `update` (ninguém mexeu lá desde então)
- hash atual != `base_hash`     → `conflict`
- nunca sincronizou, mas existe nos dois → `conflict`

**`base_hash` é sobre o documento do SERVIDOR, não sobre o payload
local.** Os dois têm formas diferentes — o servidor devolve metadados
completos, o payload é o subconjunto do PUT —, então compará-los
cruzados nunca casaria e tudo viraria conflito.

## TOCTOU, dito e não escondido

Entre o GET do plano e o PUT da aplicação existe uma janela em que outra
pessoa pode escrever. O CAS de `params_version` do servidor protege o
documento do app contra lost update, mas aceita de bom grado a sua
escrita por cima da dela — as duas são legais. **Não há como tornar esta
sincronização atômica sem capacidade nova no servidor** (PUT condicional
com `If-Match`), o que seria mudança de contrato. A janela é estreita, é
aceita, e o caso comum — conflito já existente no momento do plano — é
tratado.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from param_manager.local_store import payload_hash

ACAO_CRIAR = 'create'
ACAO_ATUALIZAR = 'update'
ACAO_CONFLITO = 'conflict'

ACOES_APLICAVEIS = frozenset({ACAO_CRIAR, ACAO_ATUALIZAR})


def classificar_param(
    registro_local: Dict[str, Any], doc_remoto: Optional[Dict[str, Any]]
) -> tuple[str, str]:
    """
    Decide o que fazer com um parâmetro. Devolve `(ação, motivo)`.

    O motivo é texto para humano: é o que o front mostra numa tela de
    conflito, e o que aparece no log de quem sincroniza por script.
    """
    base_hash = registro_local.get('base_hash')

    if doc_remoto is None:
        return ACAO_CRIAR, 'não existe no servidor'

    if not base_hash:
        return (
            ACAO_CONFLITO,
            'existe nos dois lados e nunca foi sincronizado por aqui, '
            'então não dá para saber qual versão é a mais nova',
        )

    if payload_hash(doc_remoto) == base_hash:
        return ACAO_ATUALIZAR, 'servidor inalterado desde a última sincronia'

    return (
        ACAO_CONFLITO,
        'o servidor mudou depois da última sincronia feita por aqui',
    )


def montar_plano(
    pendentes: List[Dict[str, Any]],
    remotos_por_app: Dict[str, Dict[str, Any]],
    apps_remotos: set,
) -> Dict[str, Any]:
    """
    Monta o plano de sincronização. **Não aplica nada.**

    `remotos_por_app` é `{app: {param: doc_do_servidor}}` — o que o GET
    devolveu. `apps_remotos` é o conjunto de apps que já existem lá.

    Os apps a criar saem primeiro de propósito: empurrar parâmetro para
    um app inexistente resulta em 404, então a ordem é parte do plano e
    não detalhe da aplicação.
    """
    apps_a_criar = sorted({
        registro['app']
        for registro in pendentes
        if registro['app'] not in apps_remotos
    })

    itens: List[Dict[str, Any]] = []
    for registro in pendentes:
        app = registro['app']
        nome = registro['name']
        doc_remoto = (remotos_por_app.get(app) or {}).get(nome)
        acao, motivo = classificar_param(registro, doc_remoto)
        itens.append({
            'app': app,
            'name': nome,
            'action': acao,
            'reason': motivo,
            'local': registro.get('payload'),
            'remote': doc_remoto,
        })

    return {
        'generated_at': time.time(),
        'apps_to_create': apps_a_criar,
        'params': itens,
        'summary': {
            'create': sum(1 for i in itens if i['action'] == ACAO_CRIAR),
            'update': sum(1 for i in itens if i['action'] == ACAO_ATUALIZAR),
            'conflict': sum(
                1 for i in itens if i['action'] == ACAO_CONFLITO
            ),
        },
    }


def itens_aplicaveis(plano: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Só o que o plano marcou como criar ou atualizar.

    Conflito **nunca** entra: resolvê-lo é decisão de quem opera, não da
    biblioteca. Quem quiser forçar reescreve a ação do item para
    `update` antes de aplicar, e aí a escolha é explícita e rastreável.
    """
    return [
        item
        for item in (plano.get('params') or [])
        if item.get('action') in ACOES_APLICAVEIS
    ]
