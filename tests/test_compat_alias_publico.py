"""
Compatibilidade do nome público que foi traduzido.

`ParamNaoEncontradoError` é o nome publicado no PyPI e usado em código
de terceiros. Ao padronizar os símbolos em inglês ele virou
`ParamNotFoundError`, com o nome antigo mantido como alias da MESMA
classe. Este arquivo existe para que essa promessa quebre um teste, e
não a aplicação de alguém.

FIX-PM-14
"""

import param_manager
from param_manager import ParamNaoEncontradoError, ParamNotFoundError


def test_alias_e_a_mesma_classe_e_nao_uma_subclasse():
    """
    Identidade, não parentesco.

    Se fosse subclasse, `except ParamNaoEncontradoError` deixaria de
    capturar o que a lib levanta (que seria a classe-mãe) — que é
    exatamente a quebra silenciosa que o alias existe para evitar.
    """
    assert ParamNaoEncontradoError is ParamNotFoundError


def test_nome_antigo_continua_exportado():
    """O `from param_manager import ...` de código antigo não quebra."""
    assert 'ParamNaoEncontradoError' in param_manager.__all__
    assert 'ParamNotFoundError' in param_manager.__all__


def test_except_com_nome_antigo_captura_o_que_a_lib_levanta():
    """A prova de ponta a ponta: o `except` de terceiros ainda casa."""
    try:
        raise ParamNotFoundError('404')
    except ParamNaoEncontradoError as e:
        assert str(e) == '404'
    else:  # pragma: no cover
        raise AssertionError('o alias deixou de capturar')
