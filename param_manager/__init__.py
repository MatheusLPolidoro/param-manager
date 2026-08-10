# ██████╗  █████╗ ██████╗  █████╗ ███╗   ███╗
# ██╔══██╗██╔══██╗██╔══██╗██╔══██╗████╗ ████║
# ██████╔╝███████║██████╔╝███████║██╔████╔██║
# ██╔═══╝ ██╔══██║██╔══██╗██╔══██║██║╚██╔╝██║
# ██║     ██║  ██║██║  ██║██║  ██║██║ ╚═╝ ██║
# ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
# ███╗   ███╗ █████╗ ███╗   ██╗ █████╗  ██████╗ ███████╗██████╗
# ████╗ ████║██╔══██╗████╗  ██║██╔══██╗██╔════╝ ██╔════╝██╔══██╗
# ██╔████╔██║███████║██╔██╗ ██║███████║██║  ███╗█████╗  ██████╔╝
# ██║╚██╔╝██║██╔══██║██║╚██╗██║██╔══██║██║   ██║██╔══╝  ██╔══██╗
# ██║ ╚═╝ ██║██║  ██║██║ ╚████║██║  ██║╚██████╔╝███████╗██║  ██║
# ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
"""
ParamManager
~~~~~~~~~~~~~~~
Biblioteca para gerenciamento de parâmetros.

"""
from param_manager.manager import (
    ParamManager,
    ParamNaoEncontradoError,
    ParamNotFoundError,
)

__author__ = 'MatheusLPolidoro'
__version__ = '0.5.0'
# ParamNaoEncontradoError é alias da MESMA classe que ParamNotFoundError,
# mantido no __all__ porque é o nome já publicado no PyPI.
__all__ = [
    'ParamManager',
    'ParamNaoEncontradoError',
    'ParamNotFoundError',
]
