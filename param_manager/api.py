"""
Superfície headless — pensada para um front, hoje o PyTauri.

Camada fina sobre o `ParamManager`, com três garantias que a classe não
dá e que um front precisa:

1. **Entrada e saída são dicts simples**, com forma documentada. Sem
   pydantic: arrastar `pydantic-core` — wheel Rust — para todo host que
   instala esta lib só para *ler* parâmetro seria caro, e ser embutível é
   o produto. O app PyTauri declara os modelos dele e valida na borda;
   o `@commands.command` aceita tanto `body: BaseModel` quanto tipos
   simples, então nada aqui obriga a escolha.
2. **Cópia profunda na fronteira.** `get_all_params` devolve, para tipos
   não sensíveis, o MESMO objeto guardado em `self._cache` — aliasing
   documentado e observável, que não dá para mudar sem quebrar contrato.
   Atravessando IPC, a serialização roda fora de qualquer lock e pode
   pegar o dict enquanto outra thread o muta: `RuntimeError: dictionary
   changed size during iteration` no meio de serializar. Por isso a
   superfície do front é OUTRA função, que copia — e não uma mudança em
   `get_all_params`.
3. **Erro vira dado.** Um comando de IPC que levanta atravessa a ponte
   como stack trace; aqui toda função devolve `{'ok': bool, ...}`, para
   o front decidir o que mostrar.

## Bloqueante por contrato

Tudo aqui é síncrono e bloqueia: `requests` com timeout, PBKDF2 de 100
mil iterações **por parâmetro sensível** (~50–100 ms cada) e TinyDB
reescrevendo o arquivo inteiro a cada gravação. **Chame de fora do event
loop** — `anyio.to_thread.run_sync` ou o portal do PyTauri. Não há
`async def` nesta biblioteca de propósito: uma pilha async numa lib cuja
suíte inteira é síncrona seria mudança de natureza, não de superfície.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from param_manager.local_store import (
    ESTADO_CONFLICT,
    ESTADO_REJECTED,
    ESTADO_SYNCED,
    ESTADOS_PENDENTES,
)
from param_manager.manager import MODO_LOCAL, ParamManager
from param_manager.type_catalog import validar_advisory


def _copia(valor: Any) -> Any:
    """
    Cópia profunda na fronteira do IPC.

    Não é zelo: sem ela o front serializa o dict vivo do cache enquanto
    outra thread pode estar mutando-o.
    """
    return copy.deepcopy(valor)


def _ok(**dados: Any) -> Dict[str, Any]:
    return {'ok': True, **dados}


def _erro(exc: Exception) -> Dict[str, Any]:
    return {
        'ok': False,
        'error': str(exc),
        'error_type': type(exc).__name__,
    }


def _manager(instance_name: str) -> ParamManager:
    """
    Recupera a instância nomeada, exigindo que ela já tenha sido criada.

    **Não constrói por engano.** `ParamManager.get_instance` criaria uma
    instância nova com os defaults — sem URL, em modo remoto — e o front
    passaria a operar contra uma sessão que ninguém configurou, lendo
    vazio e falhando toda escrita com uma mensagem sobre rede. Errar o
    `instance_name` é engano comum num front, e o sintoma precisa dizer
    o que aconteceu.
    """
    instancia = ParamManager._instances.get(instance_name)
    if instancia is None or not getattr(instancia, '_initialized', False):
        raise LookupError(
            f'Sessão {instance_name!r} não foi configurada. '
            f'Chame api.configure(instance_name=...) antes.'
        )
    return instancia


def configure(instance_name: str = 'default', **config: Any) -> Dict[str, Any]:
    """
    Constrói a instância nomeada. Chame uma vez, na subida do front.

    Aceita os mesmos argumentos do construtor, inclusive `mode`. Trocar
    de modo depois exige instância NOVA: `__init__` faz early-return
    quando já inicializada, e essa guarda existe para impedir
    reconfiguração de instância viva. O front que quiser um botão de
    "virar a chave" deve sincronizar, guardar a preferência no settings
    DELE e reconstruir com outro `instance_name`.
    """
    try:
        manager = ParamManager.get_instance(
            instance_name=instance_name, **config
        )
        return _ok(instance_name=instance_name, mode=manager.mode)
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def describe_session(instance_name: str = 'default') -> Dict[str, Any]:
    """Modo em vigor e se há rascunho local — o cabeçalho de uma UI."""
    try:
        manager = _manager(instance_name)
        return _ok(
            instance_name=instance_name,
            mode=manager.mode,
            has_local_store=manager._local_store is not None,
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


# ------------------------------------------------------------ leitura


def list_apps(instance_name: str = 'default') -> Dict[str, Any]:
    try:
        return _ok(apps=_copia(_manager(instance_name).list_apps()['apps']))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def _resumo_param(
    nome: str,
    payload: Dict[str, Any],
    estado: str,
    updated_at: Optional[float] = None,
    last_error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Metadado de um parâmetro: tudo do payload **menos o valor**.

    A exclusão é por lista negra de um campo só, e não por lista branca
    dos campos conhecidos. A diferença não é estilo: uma lista branca
    silenciosamente descarta `user_editable`, `max_length` e
    `referenced_params`, e um front que leia daqui para preencher o
    formulário de edição devolve esses campos vazios no próximo PUT —
    **apagando metadado que o usuário nunca tocou**. Foi exatamente o que
    aconteceu, e é a razão desta função existir nesta forma.

    `value` fica de fora porque a tabela não o mostra: trazê-lo faria
    envelope de `secret` atravessar o IPC a cada redesenho de linha.
    """
    # Um parâmetro cujo documento não seja dict não é forma esperada, mas
    # é o tipo de coisa que um servidor antigo pode devolver — e cair
    # aqui com `AttributeError` transformaria uma listagem inteira em
    # erro por causa de uma linha.
    if not isinstance(payload, dict):
        payload = {}
    metadado = {
        chave: valor for chave, valor in payload.items() if chave != 'value'
    }
    resumo = {
        'name': nome,
        **_copia(metadado),
        'state': estado,
        'last_error': last_error,
    }
    # Só sobrescreve quando o chamador tem uma data melhor. O sidecar tem
    # (a sua, de gravação local); o servidor manda a dele no próprio
    # payload, e escrever `None` por cima apagava a data em modo remoto —
    # a coluna "atualizado" saía como travessão para tudo.
    if updated_at is not None or 'updated_at' not in resumo:
        resumo['updated_at'] = updated_at
    return resumo


def list_params(app: str, instance_name: str = 'default') -> Dict[str, Any]:
    """
    Metadado dos parâmetros do app, um por linha, **sem o valor**.

    Devolve todo o resto do payload — tipo, descrição, `user_editable`,
    limites, `referenced_params` —, porque é daqui que um front preenche
    o formulário de edição. Omitir um campo aqui faz o PUT seguinte
    reenviá-lo vazio e **apagar metadado que ninguém tocou**.

    `value` é a única omissão, e é deliberada: a tabela não o mostra, e
    trazê-lo faria envelope de `secret` atravessar o IPC a cada redesenho
    de linha. O valor sai do `get_param`, quando o detalhe é aberto.

    A forma do retorno é a mesma nos dois modos, para a view não precisar
    saber em qual está. O que muda é a origem: no modo local o sidecar,
    que carrega o estado de sincronização; no remoto o próprio servidor,
    onde tudo que existe está sincronizado por definição.
    """
    try:
        manager = _manager(instance_name)
        if manager.mode != MODO_LOCAL:
            documentos = manager.get_all_params(app) or {}
            return _ok(
                app=app,
                params=[
                    _resumo_param(nome, documentos[nome], ESTADO_SYNCED)
                    for nome in sorted(documentos)
                ],
            )

        return _ok(
            app=app,
            params=[
                _resumo_param(
                    registro.get('name'),
                    registro.get('payload') or {},
                    registro.get('state'),
                    registro.get('updated_at'),
                    registro.get('last_error'),
                )
                for registro in manager._local_store.list_params(app)
            ],
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def validate_param(
    value: Any,
    param_type: str,
    instance_name: str = 'default',
    **metadata: Any,
) -> Dict[str, Any]:
    """
    Avisos que o servidor provavelmente transformaria em 422.

    **Conselho, nunca veto** — mesma promessa de `validar_advisory`, que
    faz o trabalho. `warnings` vazio significa "nada suspeito", não
    "aprovado": o catálogo pode estar velho, e regras que dependem do app
    inteiro, como `reference`, não são verificáveis do lado do cliente.

    Existe porque a validação já rodava e **não chegava a lugar nenhum**:
    era emitida como `logger.warning`, só no modo local e só depois da
    gravação. Quem opera por uma tela descobria o problema no fim de uma
    sincronização inteira. Aqui ela roda antes, nos dois modos — a
    checagem é contra o catálogo de tipos, não contra a rede.

    Não grava nada e não fala com o servidor.
    """
    try:
        manager = _manager(instance_name)
        payload = {
            'value': value,
            'type': param_type,
            **{
                chave: valor
                for chave, valor in metadata.items()
                if valor is not None
            },
        }
        return _ok(
            warnings=validar_advisory(payload, manager._type_catalog())
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def get_all_params(
    app: str, instance_name: str = 'default'
) -> Dict[str, Any]:
    """
    Parâmetros do app, em cópia própria.

    A cópia é o motivo desta função existir em vez de o front chamar
    `ParamManager.get_all_params` direto.
    """
    try:
        return _ok(
            app=app, params=_copia(_manager(instance_name).get_all_params(app))
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def get_param(
    app: str, name: str, instance_name: str = 'default'
) -> Dict[str, Any]:
    try:
        valor = _manager(instance_name).get_param(app, name)
        return _ok(app=app, name=name, value=_copia(valor))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


# ------------------------------------------------------------- escrita


def create_app(
    name: str,
    description: Optional[str] = None,
    instance_name: str = 'default',
) -> Dict[str, Any]:
    try:
        return _ok(result=_copia(_manager(instance_name).create_app(
            name, description
        )))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def upsert_param(
    app: str,
    name: str,
    value: Any,
    param_type: str,
    instance_name: str = 'default',
    **metadata: Any,
) -> Dict[str, Any]:
    """
    Grava um parâmetro. `metadata` aceita description, limites e afins.

    Tipos sensíveis falham aqui em modo local, com a mensagem explicando
    que a cifragem acontece no servidor — o front deve mostrá-la como
    está, não traduzi-la.
    """
    try:
        return _ok(result=_copia(_manager(instance_name).upsert_params(
            app, name, value=value, param_type=param_type, **metadata
        )))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def delete_param(
    app: str, name: str, instance_name: str = 'default'
) -> Dict[str, Any]:
    try:
        return _ok(
            result=_copia(_manager(instance_name).delete_param(app, name))
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def delete_app(app: str, instance_name: str = 'default') -> Dict[str, Any]:
    try:
        return _ok(result=_copia(_manager(instance_name).delete_app(app)))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


# ------------------------------------------------------- sincronização


def sync_status(
    app: Optional[str] = None, instance_name: str = 'default'
) -> Dict[str, Any]:
    """
    Contagem por estado, sem tocar na rede.

    É o que um indicador de "há N alterações não enviadas" consome, e por
    isso não pode custar uma requisição.
    """
    try:
        manager = _manager(instance_name)
        if manager.mode != MODO_LOCAL:
            return _ok(mode=manager.mode, pending=0, rejected=0, conflict=0)

        store = manager._local_store
        if app is not None:
            registros: List[Dict[str, Any]] = store.list_params(app)
        else:
            registros = [
                registro
                for nome in (a['name'] for a in store.list_apps())
                for registro in store.list_params(nome)
            ]
        estados = [r.get('state') for r in registros]
        return _ok(
            mode=manager.mode,
            pending=sum(1 for e in estados if e in ESTADOS_PENDENTES),
            rejected=estados.count(ESTADO_REJECTED),
            conflict=estados.count(ESTADO_CONFLICT),
            total=len(estados),
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def sync_plan(
    app: Optional[str] = None, instance_name: str = 'default'
) -> Dict[str, Any]:
    """
    Fase 1. Devolve o plano para a tela de diff. **Não grava nada.**

    Bloqueia: fala com o servidor.
    """
    try:
        return _ok(plan=_copia(_manager(instance_name).sync_plan(app)))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def sync_apply(
    plan: Dict[str, Any], instance_name: str = 'default'
) -> Dict[str, Any]:
    """
    Fase 2. Aplica só o que o plano marcou como aplicável.

    Recebe o plano de volta do front — inclusive com conflitos que o
    operador tenha promovido a `update` de propósito. É por isso que a
    decisão fica registrada no plano, e não num parâmetro solto.
    """
    try:
        return _ok(result=_copia(_manager(instance_name).sync_apply(plan)))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def refresh_type_catalog(instance_name: str = 'default') -> Dict[str, Any]:
    """Busca o catálogo vivo e o guarda para validar offline."""
    try:
        return _ok(
            catalog=_copia(_manager(instance_name).refresh_type_catalog())
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)


def type_catalog(instance_name: str = 'default') -> Dict[str, Any]:
    """Catálogo em uso: o guardado, senão o embarcado. Sem rede."""
    try:
        return _ok(catalog=_copia(_manager(instance_name)._type_catalog()))
    except Exception as exc:  # noqa: BLE001
        return _erro(exc)
