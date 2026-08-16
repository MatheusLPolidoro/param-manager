"""
Front desktop do `param-manager`, em PyTauri.

Instalado pelo extra: ``pip install "param-manager[front]"``.

## Por que é um subpacote, e não um projeto à parte

O front consome a lib e nada mais consome o front. Publicá-lo como
distribuição própria significaria versionar e liberar dois artefatos que
mudam juntos — o custo que cliente e servidor já pagam neste produto por
serem, esses sim, liberados em ritmos diferentes.

## Como o desacoplamento é sustentado

Não por boa vontade: `tests/test_front_desacoplamento.py` percorre a AST
deste subpacote e reprova se

1. qualquer módulo daqui importar de `param_manager` algo que não seja
   `param_manager.api` — a superfície headless é a única porta; e
2. `pytauri` aparecer fora de `bridge.py` e `launcher.py`.

A segunda regra parece detalhe de organização e não é. `pytauri_wheel` é
extensão compilada que liga contra WebView2/gtk e sequer *importa* numa
imagem `python:3-slim`. Mantendo os handlers livres dele, a suíte inteira
do front roda nos jobs de CI que já existem, sem instalar o extra e sem
uma biblioteca de sistema sequer.
"""

from param_manager.front.version import __version__

__all__ = ['__version__']
