"""
A ponte com o PyTauri — e o único lugar do subpacote que o conhece.

Registra cada entrada de `handlers.HANDLERS` como um comando de IPC,
embrulhado em `async` que joga a chamada numa thread. O embrulho não é
cerimônia: **tudo em `param_manager.api` bloqueia** — `requests` com
timeout, PBKDF2 de cem mil iterações por parâmetro sensível, TinyDB
reescrevendo o arquivo inteiro a cada gravação. Chamar isso direto no
event loop congelaria a janela no meio de um `upsert`.

Isolar o registro aqui é o que mantém `handlers.py` importável — e
testável — sem `pytauri_wheel`, que é extensão nativa ligada a
WebView2/gtk e nem carrega numa imagem `slim`.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Dict

from anyio import to_thread
from pytauri import Commands

from param_manager.front.handlers import HANDLERS


def _registrar(commands: Commands, nome: str) -> None:
    """
    Cria o comando assíncrono de um handler.

    A função é gerada dentro deste escopo de propósito: fechar sobre a
    variável do laço faria todos os comandos chamarem o último handler
    registrado, que é o defeito clássico deste padrão e silencioso aqui —
    a janela abre, os botões respondem, e todos fazem a mesma coisa.
    """
    handler = HANDLERS[nome]

    async def comando(body: Dict[str, Any]) -> Dict[str, Any]:
        return await to_thread.run_sync(partial(handler, body))

    comando.__name__ = nome
    commands.command(nome)(comando)


def montar_comandos() -> Commands:
    """Todos os handlers registrados, na ordem em que foram declarados."""
    commands = Commands()
    for nome in HANDLERS:
        _registrar(commands, nome)
    return commands
