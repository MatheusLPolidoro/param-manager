"""
Handlers do front — a tradução entre o corpo do IPC e `param_manager.api`.

Três regras que definem esta camada:

1. **Não tem regra de negócio.** Cada handler extrai campos do corpo e
   chama a função homônima da `api`. Nome diferente aqui seria o começo
   de uma segunda API, com duas verdades sobre a mesma operação.
2. **Nenhum handler levanta.** A `api` já devolve `{'ok': False, ...}`
   para as falhas dela; o `_handler` fecha o resto — corpo sem a chave
   esperada, tipo errado — para que nada atravesse a ponte como stack
   trace.
3. **São síncronos.** Quem os torna assíncronos é o `bridge`, que os
   joga numa thread. Assim este módulo não importa `anyio` nem `pytauri`
   e roda na suíte de CI sem o extra instalado.
"""

from __future__ import annotations

from functools import wraps
from importlib.metadata import version
from typing import Any, Callable, Dict, Iterable, Tuple

from param_manager import api
from param_manager.front import session
from param_manager.front.version import __version__ as versao_front

Corpo = Dict[str, Any]
Resposta = Dict[str, Any]
Handler = Callable[[Corpo], Resposta]

HANDLERS: Dict[str, Handler] = {}


def _falha(exc: Exception) -> Resposta:
    """Mesma forma do `api._erro`, para o front ter um caminho de erro só."""
    return {
        'ok': False,
        'error': str(exc),
        'error_type': type(exc).__name__,
    }


def _handler(nome: str) -> Callable[[Handler], Handler]:
    def decorador(func: Handler) -> Handler:
        @wraps(func)
        def embrulho(body: Corpo) -> Resposta:
            try:
                return func(body or {})
            except Exception as exc:  # noqa: BLE001
                return _falha(exc)

        HANDLERS[nome] = embrulho
        return embrulho

    return decorador


def _repassa(
    nome: str,
    func: Callable[..., Resposta],
    obrigatorios: Iterable[str] = (),
    opcionais: Iterable[str] = (),
) -> None:
    """
    Registra um handler que só repassa campos nomeados para a `api`.

    Campo obrigatório ausente vira `KeyError`, que o `_handler` converte
    em `ok: false` — mensagem curta e específica, em vez de o `TypeError`
    de um `**body` cru.
    """
    campos_obrigatorios: Tuple[str, ...] = tuple(obrigatorios)
    campos_opcionais: Tuple[str, ...] = tuple(opcionais)

    def executar(body: Corpo) -> Resposta:
        args: Dict[str, Any] = {
            campo: body[campo] for campo in campos_obrigatorios
        }
        for campo in campos_opcionais:
            if campo in body:
                args[campo] = body[campo]
        args['instance_name'] = body.get('instance_name', 'default')
        return func(**args)

    _handler(nome)(executar)


# ------------------------------------------------------------- sessão da lib


@_handler('configure')
def configure(body: Corpo) -> Resposta:
    """
    Constrói a instância nomeada com o que a tela de sessão preencheu.

    Guarda o nome escolhido nas preferências do front para a próxima
    subida já vir configurada — e é só isso que o front persiste: URL,
    usuário e senha continuam sendo problema de env e do `.env` da lib,
    que é onde já estavam.
    """
    config = dict(body)
    instance_name = config.pop('instance_name', 'default')
    resposta = api.configure(instance_name=instance_name, **config)
    if resposta.get('ok'):
        session.salvar(last_instance=instance_name)
    return resposta


_repassa('describe_session', api.describe_session)


# ------------------------------------------------------------------ leitura

_repassa('list_apps', api.list_apps)
_repassa('list_params', api.list_params, ('app',))
_repassa('get_all_params', api.get_all_params, ('app',))
_repassa('get_param', api.get_param, ('app', 'name'))


@_handler('validate_param')
def validate_param(body: Corpo) -> Resposta:
    """Avisos do catálogo antes de gravar. Não grava e não usa rede."""
    dados = dict(body)
    value = dados.pop('value')
    param_type = dados.pop('param_type')
    instance_name = dados.pop('instance_name', 'default')
    dados.pop('app', None)
    dados.pop('name', None)
    return api.validate_param(
        value, param_type, instance_name=instance_name, **dados
    )


# ------------------------------------------------------------------ escrita

_repassa('create_app', api.create_app, ('name',), ('description',))
_repassa('delete_param', api.delete_param, ('app', 'name'))
_repassa('delete_app', api.delete_app, ('app',))


@_handler('upsert_param')
def upsert_param(body: Corpo) -> Resposta:
    """
    Grava um parâmetro. O que sobra do corpo vira metadado.

    `description`, `min_length`, `max_length` e afins são opcionais e a
    lib distingue "não enviado" de "enviado como nulo" — por isso o resto
    do corpo é repassado como veio, sem preencher default nenhum aqui.
    """
    dados = dict(body)
    app = dados.pop('app')
    name = dados.pop('name')
    value = dados.pop('value')
    param_type = dados.pop('param_type')
    instance_name = dados.pop('instance_name', 'default')
    return api.upsert_param(
        app,
        name,
        value,
        param_type,
        instance_name=instance_name,
        **dados,
    )


# ------------------------------------------------------------ sincronização

_repassa('sync_status', api.sync_status, (), ('app',))
_repassa('sync_plan', api.sync_plan, (), ('app',))
_repassa('sync_apply', api.sync_apply, ('plan',))


# ----------------------------------------------------------------- catálogo

_repassa('refresh_type_catalog', api.refresh_type_catalog)
_repassa('type_catalog', api.type_catalog)


# ----------------------------------------------- preferências do front (UI)


@_handler('ui_prefs_get')
def ui_prefs_get(body: Corpo) -> Resposta:
    del body
    return {'ok': True, 'prefs': session.carregar()}


@_handler('ui_prefs_set')
def ui_prefs_set(body: Corpo) -> Resposta:
    return {'ok': True, 'prefs': session.salvar(**body)}


@_handler('ui_bootstrap')
def ui_bootstrap(body: Corpo) -> Resposta:
    """
    Tudo que a primeira pintura precisa, numa chamada só.

    Cinco round-trips antes do primeiro pixel é o que faz um app parecer
    lento mesmo sendo rápido.
    """
    del body
    prefs = session.carregar()
    return {
        'ok': True,
        'prefs': prefs,
        'language': prefs.get('language') or session.idioma_do_sistema(),
        'system_language': session.idioma_do_sistema(),
        'languages': list(session.IDIOMAS_SUPORTADOS),
        'front_version': versao_front,
        'lib_version': _versao_lib(),
    }


def _versao_lib() -> str:
    """
    Versão da lib pelos metadados da distribuição, não pelo `__version__`.

    Importar `param_manager` na raiz para ler o atributo furaria a regra
    de import único que este subpacote se impõe — e o metadado responde a
    mesma pergunta sem acoplar a nada.
    """
    try:
        return version('param-manager')
    except Exception:  # noqa: BLE001
        return 'desconhecida'
