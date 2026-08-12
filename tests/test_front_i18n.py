"""
Tradução: nenhuma chave pode faltar num dos idiomas.

Chave ausente não quebra nada — `t()` devolve a própria chave — e é
exatamente por isso que precisa de teste: o sintoma é `params.coluna.nome`
escrito na tela de alguém que não fala português, e ninguém percebe até
lá.

O teste confere as duas direções (paridade entre catálogos) e a cobertura
(toda chave usada no HTML e no JS existe nos dois).

FIX-PM-22
"""

import json
import re
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parent.parent
    / 'param_manager'
    / 'front'
    / 'assets'
)
IDIOMAS = ('pt-BR', 'en')

# Chaves montadas em tempo de execução — `t(`estado.${estado}`)` e afins.
# Não dá para extraí-las do fonte, então a lista de sufixos fica aqui, ao
# lado do motivo. Acrescentar um estado novo sem acrescentar aqui é
# exatamente o esquecimento que este arquivo existe para pegar.
FAMILIAS_DINAMICAS = {
    'estado.': ('draft', 'dirty', 'synced', 'conflict', 'rejected'),
    'estado.{}.explicacao': (
        'draft', 'dirty', 'synced', 'conflict', 'rejected',
    ),
    'modo.': ('local', 'remote'),
    'modo.{}.explicacao': ('local', 'remote'),
    'sync.acao.': ('create', 'update', 'conflict'),
    'idioma.': IDIOMAS,
    'prefs.tema.': ('system', 'light', 'dark'),
    # Campos do editor de `user`/`users`, montados por `campos.js`.
    'params.user.': ('user', 'password', 'user_id', 'status'),
}

# `params.placeholder.X` e `params.dica.X` são consultados por tipo, e
# **nem todo tipo tem os dois** — `campos.js` mostra a dica só quando ela
# existe, e o `t()` devolvendo a própria chave é o sinal de ausência. Por
# isso a checagem aqui é ao contrário: toda chave declarada precisa
# apontar para um tipo que o catálogo embarcado conhece, para pegar
# tradução escrita para um tipo que não existe.
PREFIXOS_POR_TIPO = ('params.placeholder.', 'params.dica.')


def catalogo(idioma):
    caminho = ASSETS / 'i18n' / f'{idioma}.json'
    return json.loads(caminho.read_text(encoding='utf-8'))


def chaves_do_html():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    chaves = set(re.findall(r'data-i18n="([^"]+)"', html))
    for bloco in re.findall(r'data-i18n-attr="([^"]+)"', html):
        for par in bloco.split(','):
            partes = par.split(':')
            if len(partes) == 2:
                chaves.add(partes[1].strip())
    return chaves


def chaves_do_js():
    chaves = set()
    for arquivo in (ASSETS / 'js').rglob('*.js'):
        fonte = arquivo.read_text(encoding='utf-8')
        chaves.update(re.findall(r"\bt\('([^']+)'", fonte))
    return chaves


def chaves_dinamicas():
    esperadas = set()
    for molde, sufixos in FAMILIAS_DINAMICAS.items():
        for sufixo in sufixos:
            if '{}' in molde:
                esperadas.add(molde.format(sufixo))
            else:
                esperadas.add(f'{molde}{sufixo}')
    return esperadas


def test_os_catalogos_tem_o_mesmo_conjunto_de_chaves():
    conjuntos = {idioma: set(catalogo(idioma)) for idioma in IDIOMAS}
    referencia = conjuntos[IDIOMAS[0]]

    for idioma in IDIOMAS[1:]:
        faltando = referencia - conjuntos[idioma]
        sobrando = conjuntos[idioma] - referencia
        assert not faltando, f'{idioma} não tem: {sorted(faltando)}'
        assert not sobrando, f'{idioma} tem a mais: {sorted(sobrando)}'


@pytest.mark.parametrize('idioma', IDIOMAS)
def test_nenhum_valor_esta_vazio(idioma):
    vazias = [
        chave
        for chave, texto in catalogo(idioma).items()
        if not str(texto).strip()
    ]

    assert not vazias, f'{idioma} tem chaves sem texto: {vazias}'


@pytest.mark.parametrize('idioma', IDIOMAS)
def test_toda_chave_usada_existe(idioma):
    usadas = chaves_do_html() | chaves_do_js() | chaves_dinamicas()
    ausentes = sorted(usadas - set(catalogo(idioma)))

    assert not ausentes, f'{idioma} não traduz: {ausentes}'


@pytest.mark.parametrize('idioma', IDIOMAS)
def test_chave_por_tipo_aponta_para_tipo_existente(idioma):
    """
    Placeholder ou dica escritos para um tipo que o catálogo não tem.

    É tradução que nunca aparece — e que ninguém nota, porque a ausência
    é silenciosa por desenho. O caso concreto: o projeto de referência
    deste editor usa `number`/`decimal`/`boolean`, e o catálogo daqui usa
    `int`/`float`/`bool`.
    """
    from param_manager.type_catalog import CATALOGO_EMBARCADO

    conhecidos = set(CATALOGO_EMBARCADO['types'])
    invalidas = [
        chave
        for chave in catalogo(idioma)
        for prefixo in PREFIXOS_POR_TIPO
        if chave.startswith(prefixo)
        and chave[len(prefixo):] not in conhecidos
    ]

    assert not invalidas, f'{idioma} traduz tipo inexistente: {invalidas}'


def test_o_html_nao_tem_texto_solto_nos_rotulos():
    """
    Todo `data-i18n` precisa vir de um elemento sem texto pré-escrito.

    Texto no HTML sobrevive até a primeira tradução rodar e reaparece se
    ela falhar — e aí a interface fica bilíngue por acidente.
    """
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    suspeitos = re.findall(
        r'data-i18n="[^"]+"[^>]*>\s*([^\s<][^<]*)</', html
    )

    assert not suspeitos, f'texto escrito no HTML: {suspeitos}'


def test_placeholders_batem_entre_os_idiomas():
    """
    `{nome}` numa língua e não na outra vira chave literal na tela.

    O `t()` só troca o que encontra: um placeholder que existe só no
    inglês aparece cru para quem usa inglês.
    """
    referencia = catalogo(IDIOMAS[0])
    for idioma in IDIOMAS[1:]:
        outro = catalogo(idioma)
        for chave, texto in referencia.items():
            esperados = set(re.findall(r'\{(\w+)\}', texto))
            obtidos = set(re.findall(r'\{(\w+)\}', outro[chave]))
            assert esperados == obtidos, (
                f'{chave}: {IDIOMAS[0]} usa {esperados}, '
                f'{idioma} usa {obtidos}'
            )
