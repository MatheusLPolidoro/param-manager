"""
Confronta o OpenAPI do servidor com o que esta biblioteca realmente chama.

Metade cliente da CT-1. A metade servidora
(fast-param-manager/tests/test_openapi_contrato.py) congela o esquema
publicado; aqui a pergunta é outra e ninguém mais a faz: **o servidor que
está no ar ainda serve o que este cliente chama?**

Nenhum job cruza os dois repositórios, e cliente e servidor são liberados
em separado. Sem isto, o servidor renomeia uma rota, atualiza os próprios
testes junto, fica verde — e só o `param-manager` já publicado no PyPI
quebra, em produção.

**Este teste se pula sozinho.** Ele só roda quando a variável
`PARAM_MANAGER_OPENAPI` aponta para um `openapi.json`; o job `testes` do
servidor publica esse arquivo como artefato. Sem a variável, pular é o
comportamento certo: a suíte do cliente não pode depender de ter um
servidor por perto.

    $env:PARAM_MANAGER_OPENAPI = 'C:\\caminho\\openapi.json'
    pytest tests/test_integracao_contrato_servidor.py -m integracao -v

FIX-PM-15
"""

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integracao

# Cada entrada é um par metodo+caminho que `manager.py` chama, com o
# status que ele exige. O cliente compara `status_code != HTTPStatus.OK`
# de forma EXATA, então um 2xx diferente também é quebra.
#
# São oito. A contagem já foi anotada errada em dois lugares da
# documentação — aqui ela é verificável.
ROTAS_QUE_O_CLIENTE_CHAMA = {
    ('post', '/auth/token'): '200',
    ('post', '/auth/refresh'): '200',
    ('post', '/parameters/apps/'): '201',
    ('put', '/parameters/apps/{app_name}/params/'): '200',
    ('get', '/parameters/apps/{app_name}/params/'): '200',
    ('get', '/parameters/apps/{app_name}/params/{param_name}'): '200',
    ('delete', '/parameters/apps/{app_name}/params/{param_name}'): '200',
    ('delete', '/parameters/apps/{app_name}'): '200',
    # Catálogo de tipos, consumido por refresh_type_catalog(). Sem ele o
    # cliente cai no piso embarcado, que envelhece — então a rota sumir
    # degrada em silêncio, que é o pior modo de falhar.
    ('get', '/parameters/types'): '200',
}

# Chaves de topo lidas pelo cliente, por rota. As de auth ficam de fora:
# o servidor não declara `response_model` nelas, então o esquema publica
# um objeto livre e não há o que conferir.
CHAVES_LIDAS = {
    ('put', '/parameters/apps/{app_name}/params/'): ['params'],
    ('get', '/parameters/apps/{app_name}/params/'): ['params'],
    ('get', '/parameters/apps/{app_name}/params/{param_name}'): ['param'],
}


def _carregar_spec():
    caminho = os.getenv('PARAM_MANAGER_OPENAPI')
    if not caminho:
        pytest.skip(
            'PARAM_MANAGER_OPENAPI não definida; sem esquema do servidor '
            'para conferir.'
        )
    arquivo = Path(caminho)
    if not arquivo.is_file():
        pytest.skip(f'Esquema não encontrado em {caminho}.')
    # utf-8-sig e não utf-8: neste workspace arquivo gerado com `>` no
    # PowerShell 5.1 sai com BOM, e o json.loads morre no ﻿ com uma
    # mensagem que não menciona encoding nenhum. Tolerar custa nada.
    return json.loads(arquivo.read_text(encoding='utf-8-sig'))


@pytest.fixture(scope='module')
def spec():
    return _carregar_spec()


@pytest.mark.parametrize(
    ('metodo', 'caminho'), sorted(ROTAS_QUE_O_CLIENTE_CHAMA)
)
def test_rota_chamada_pelo_cliente_existe(spec, metodo, caminho):
    """Rota renomeada ou removida derruba cliente já instalado."""
    assert caminho in spec['paths'], (
        f'O servidor não publica mais {caminho}. Esta biblioteca a chama '
        f'com URL fixa e não negocia versão.'
    )
    assert metodo in spec['paths'][caminho], (
        f'{metodo.upper()} sumiu de {caminho}.'
    )


@pytest.mark.parametrize(
    ('metodo', 'caminho'), sorted(ROTAS_QUE_O_CLIENTE_CHAMA)
)
def test_status_de_sucesso_ainda_e_o_esperado(spec, metodo, caminho):
    """
    O cliente compara o status de forma exata e levanta no que diferir.

    É a quebra mais traiçoeira do conjunto: do lado do servidor ela passa
    por "continua sendo sucesso".
    """
    operacao = spec['paths'][caminho][metodo]
    codigos = [
        c
        for c in operacao.get('responses', {})
        if c.isdigit() and c.startswith('2')
    ]
    esperado = ROTAS_QUE_O_CLIENTE_CHAMA[(metodo, caminho)]
    assert codigos == [esperado], (
        f'{metodo.upper()} {caminho} passou a responder {codigos}; este '
        f'cliente exige exatamente {esperado}.'
    )


@pytest.mark.parametrize(('metodo', 'caminho'), sorted(CHAVES_LIDAS))
def test_chaves_que_o_cliente_le_continuam_no_esquema(spec, metodo, caminho):
    """
    `res.json()['params']` e afins: chave sumida vira KeyError ou None.

    Só as de topo, e só as que o cliente de fato lê — o conteúdo de
    `params` é o dicionário do usuário e muda por natureza.
    """
    operacao = spec['paths'][caminho][metodo]
    codigo = ROTAS_QUE_O_CLIENTE_CHAMA[(metodo, caminho)]
    schema = (
        operacao['responses'][codigo]
        .get('content', {})
        .get('application/json', {})
        .get('schema', {})
    )
    ref = schema.get('$ref')
    assert ref, (
        f'{metodo.upper()} {caminho} deixou de declarar response_model; '
        f'não dá mais para conferir as chaves pelo esquema.'
    )
    nome = ref.rsplit('/', 1)[-1]
    propriedades = spec['components']['schemas'][nome]['properties']
    for chave in CHAVES_LIDAS[(metodo, caminho)]:
        assert chave in propriedades, (
            f'A chave {chave!r} sumiu de {nome}. O cliente a lê direto '
            f'do corpo da resposta.'
        )


def test_esquema_de_seguranca_continua_bearer(spec):
    """
    O cliente monta `Authorization: Bearer` na mão.

    Trocar o esquema publicado significa que ele passa a mandar uma
    credencial que o servidor não entende mais.
    """
    esquemas = spec.get('components', {}).get('securitySchemes', {})
    assert 'HTTPBearer' in esquemas, (
        f'HTTPBearer sumiu do esquema publicado: {sorted(esquemas)}.'
    )
    assert esquemas['HTTPBearer'].get('scheme') == 'bearer'
