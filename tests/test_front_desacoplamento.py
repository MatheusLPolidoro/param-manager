"""
As duas regras de import que sustentam o subpacote `front`.

Nenhuma delas é gosto de organização; cada uma paga uma conta concreta.

**Regra 1 — a única porta para a lib é `param_manager.api`.** É o que
permite reescrever o front, trocar de framework ou jogá-lo fora sem
encostar em `manager.py`. Um import de `manager`, `local_store` ou
`crypto` aqui e o front vira parte da lib sem ninguém decidir isso.

**Regra 2 — `pytauri` só em `bridge.py` e `launcher.py`.** `pytauri_wheel`
é extensão compilada ligada a WebView2/gtk: numa imagem `python:3-slim`
ela nem importa. Mantendo os handlers livres dele, a suíte inteira roda
nos jobs de CI que já existem, sem instalar o extra nem uma biblioteca de
sistema. Juntar os módulos "para simplificar" quebra o CI de um jeito que
parece problema de infraestrutura.

FIX-PM-22
"""

import ast
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parent.parent / 'param_manager' / 'front'

MODULOS_COM_PYTAURI = {'bridge.py', 'launcher.py'}


def modulos():
    return sorted(FRONT.rglob('*.py'))


def imports_de(caminho):
    """
    Todo alvo importado, qualificado, inclusive de dentro de função.

    `from param_manager import api` e `import param_manager.api` são a
    mesma coisa e precisam ser julgados igual — por isso o `ImportFrom`
    é resolvido até o nome, e não parado no módulo. Sem isso a regra
    puniria a forma idiomática e aceitaria
    `from param_manager import manager`, que é justamente o que ela
    existe para barrar.
    """
    arvore = ast.parse(caminho.read_text(encoding='utf-8'))
    encontrados = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            encontrados.extend(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            encontrados.extend(
                f'{no.module}.{alias.name}' for alias in no.names
            )
    return encontrados


def test_existem_modulos_para_conferir():
    """Guarda contra o teste passar por não ter encontrado nada."""
    assert len(modulos()) >= 5


@pytest.mark.parametrize('caminho', modulos(), ids=lambda c: c.name)
def test_a_unica_porta_para_a_lib_e_a_api(caminho):
    proibidos = [
        modulo
        for modulo in imports_de(caminho)
        if modulo.startswith('param_manager')
        and modulo != 'param_manager.api'
        and not modulo.startswith('param_manager.front')
    ]

    assert not proibidos, (
        f'{caminho.name} importa {proibidos} da lib. O front fala com '
        f'`param_manager.api` e mais nada — ver o docstring deste teste.'
    )


@pytest.mark.parametrize('caminho', modulos(), ids=lambda c: c.name)
def test_pytauri_fica_confinado_a_ponte(caminho):
    tem_pytauri = any(
        modulo.split('.')[0] in ('pytauri', 'pytauri_wheel', 'anyio')
        for modulo in imports_de(caminho)
    )

    if caminho.name in MODULOS_COM_PYTAURI:
        return

    assert not tem_pytauri, (
        f'{caminho.name} importa pytauri/anyio. Só {MODULOS_COM_PYTAURI} '
        f'podem — do contrário a suíte deixa de rodar sem o extra.'
    )


def test_handlers_importam_sem_o_extra():
    """
    A prova direta da regra 2: importar os handlers não puxa a webview.

    Se este teste falhar num ambiente sem `pytauri-wheel`, é porque
    alguém uniu as camadas de novo.
    """
    from param_manager.front import handlers

    assert handlers.HANDLERS
