"""
Catálogo de tipos de parâmetro: piso embarcado e validação *advisory*.

O servidor publica o catálogo em `GET /parameters/types`, derivado do
código dele. Aqui ele é **dado**, nunca regra reimplementada: a lib não
tem uma cópia dos validadores, só um interpretador do que o servidor
descreveu. Reimplementar `VALIDATORS` repetiria, num eixo que muda com
frequência, o problema que o envelope criptográfico já tem — duas
implementações da mesma regra em artefatos liberados separadamente.

**A validação daqui é conselho, não veto.** Quem valida de verdade é o
servidor, na sincronização. O papel deste módulo é evitar que um erro de
digitação só apareça no fim de uma sessão inteira de trabalho offline —
em especial o `max_length` padrão de 30, que recusa uma string de 40
caracteres quando o limite não vai explícito no payload.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Piso offline. Cópia do que o servidor publicava quando esta versão foi
# liberada; serve enquanto ninguém conseguiu falar com ele.
#
# **Não edite à mão para "corrigir" um tipo novo**: o caminho certo é
# `ParamManager.refresh_type_catalog()`, que busca o catálogo vivo e o
# guarda no sidecar. Este dicionário é o que sobra quando não há
# servidor, e envelhecer é o comportamento esperado dele.
CATALOGO_EMBARCADO: Dict[str, Any] = {
    'types': [
        'bool',
        'date',
        'datetime',
        'dict',
        'float',
        'int',
        'json',
        'list',
        'pattern',
        'reference',
        'secret',
        'string',
        'time',
        'user',
        'users',
    ],
    'sensitive': ['secret', 'user', 'users'],
    'defaults': {
        'min_length': 0,
        'max_length': 30,
        'min_value': 0,
        'max_value': 1_000_000,
    },
}


def _limite(payload: Dict[str, Any], catalogo: Dict[str, Any], campo: str):
    """
    Limite efetivo: o do payload quando informado, senão o default.

    Reproduz o que o servidor faz — e é aqui que mora a armadilha. O
    cliente omite do payload os campos que o chamador não informou, e o
    servidor aplica os defaults do `ParamModel` nesses casos. Quem
    valida sem esse degrau conclui que não há limite nenhum.
    """
    if campo in payload and payload[campo] is not None:
        return payload[campo]
    return (catalogo.get('defaults') or {}).get(campo)


def validar_advisory(
    payload: Dict[str, Any], catalogo: Dict[str, Any] | None = None
) -> List[str]:
    """
    Devolve os avisos que o servidor provavelmente transformaria em 422.

    **Nunca levanta e nunca bloqueia.** Lista vazia significa "nada
    suspeito", não "aprovado": o catálogo pode estar velho, e regras que
    dependem do app inteiro — como `reference`, que confere contra os
    outros parâmetros — não são verificáveis aqui.
    """
    catalogo = catalogo or CATALOGO_EMBARCADO
    avisos: List[str] = []

    tipo = payload.get('type')
    tipos = catalogo.get('types') or []
    if tipos and tipo not in tipos:
        avisos.append(
            f'tipo {tipo!r} não está no catálogo do servidor; '
            f'conhecidos: {", ".join(sorted(tipos))}'
        )

    valor = payload.get('value')

    if isinstance(valor, (str, list)):
        minimo = _limite(payload, catalogo, 'min_length')
        maximo = _limite(payload, catalogo, 'max_length')
        if minimo is not None and len(valor) < minimo:
            avisos.append(
                f'comprimento {len(valor)} é menor que o mínimo {minimo}'
            )
        if maximo is not None and len(valor) > maximo:
            avisos.append(
                f'comprimento {len(valor)} passa do máximo {maximo}; '
                f'informe max_length no upsert para elevar o limite'
            )

    # `bool` entra aqui porque é subclasse de int e o servidor também o
    # trata assim. Espelhar a regra dele importa mais do que a pureza.
    if isinstance(valor, (int, float)):
        minimo = _limite(payload, catalogo, 'min_value')
        maximo = _limite(payload, catalogo, 'max_value')
        if minimo is not None and valor < minimo:
            avisos.append(f'valor {valor} é menor que o mínimo {minimo}')
        if maximo is not None and valor > maximo:
            avisos.append(
                f'valor {valor} passa do máximo {maximo}; informe '
                f'max_value no upsert para elevar o limite'
            )

    return avisos
