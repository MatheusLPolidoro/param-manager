"""
Sobe a janela: resolve caminhos, monta o builder e roda o portal.

Junto com `bridge.py`, é o que conhece o PyTauri. Trocar de framework de
front custa reescrever estes dois arquivos — os handlers, os assets e a
`api` da lib não sabem que ele existe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

DIRETORIO_TAURI = Path(__file__).parent.absolute()
"""Equivalente ao `src-tauri` de um projeto Rust: guarda config e assets."""

MENSAGEM_SEM_EXTRA = """\
O front do param-manager não está instalado.

    pip install "param-manager[front]"

Ele também exige um runtime de webview no sistema:
  - Windows: WebView2 Runtime (Evergreen Bootstrapper)
  - Linux:   libwebkit2gtk-4.1-0, libgtk-3-0, libappindicator3-1
  - macOS:   nada, já vem no sistema
"""


def _config_dev() -> Optional[Dict[str, Any]]:
    """
    Aponta o `frontendDist` para um servidor de desenvolvimento, se houver.

    Existe para editar CSS sem reempacotar. Sem `PARAM_MANAGER_FRONT_DEV`
    definida, os assets saem do próprio pacote — que é o caminho de quem
    instalou pelo pip e o único que precisa funcionar.
    """
    servidor = os.environ.get('PARAM_MANAGER_FRONT_DEV')
    if not servidor:
        return None
    return {'build': {'frontendDist': servidor}}


def main() -> int:
    """
    Ponto de entrada do console script `param-manager-front`.

    A importação do PyTauri acontece aqui dentro, e não no topo: em nível
    de módulo, um extra ausente viraria `ModuleNotFoundError:
    pytauri_wheel` no meio de um traceback — que é uma mensagem sobre um
    pacote que o usuário nunca pediu. Adiando, a falha vira a instrução
    de instalação.
    """
    try:
        # O adiamento É o comportamento desejado, ver o docstring: por
        # isso os PLC0415 abaixo são silenciados um a um.
        from anyio.from_thread import start_blocking_portal  # noqa: PLC0415
        from pytauri_wheel.lib import (  # noqa: PLC0415
            builder_factory,
            context_factory,
        )

        from param_manager.front.bridge import (  # noqa: PLC0415
            montar_comandos,
        )
    except ImportError as exc:
        print(MENSAGEM_SEM_EXTRA, file=sys.stderr)
        print(f'Detalhe: {exc}', file=sys.stderr)
        return 1

    comandos = montar_comandos()

    with start_blocking_portal('asyncio') as portal:
        app = builder_factory().build(
            context=context_factory(
                DIRETORIO_TAURI, tauri_config=_config_dev()
            ),
            invoke_handler=comandos.generate_handler(portal),
        )
        return app.run_return()
