"""
Exceções públicas da biblioteca.

Separadas do `manager` para que um módulo possa levantá-las sem importar
o `ParamManager` inteiro — o que criaria import circular assim que a
decomposição avançar. `manager.py` reexporta os dois nomes, então
`from param_manager.manager import ...` continua funcionando.
"""

from __future__ import annotations


class ParamNotFoundError(Exception):
    """Levantada quando um parâmetro retorna 404 (não encontrado)."""

    pass


# Alias de compatibilidade. O nome em português é o que foi publicado no
# PyPI e está em uso em código de terceiros; como é a MESMA classe, e não
# uma subclasse, `except ParamNaoEncontradoError` continua capturando o
# que esta biblioteca levanta. Não remover sem uma major.
ParamNaoEncontradoError = ParamNotFoundError
