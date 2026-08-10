"""
LocalStore contra arquivo REAL em disco.

Sem mock de propósito. A suíte unitária troca TinyDB por `MagicMock`,
cujo `table.get()` devolve **o mesmo objeto** em toda chamada — um
apelidamento que o banco real não tem e que já escondeu um defeito de
persistência nesta base. Persistência se testa contra o disco.

FIX-PM-16
"""

import json
import threading

import pytest
from tinydb import TinyDB

from param_manager.local_store import (
    ESTADO_CONFLICT,
    ESTADO_DIRTY,
    ESTADO_DRAFT,
    ESTADO_REJECTED,
    ESTADO_SYNCED,
    ORIGEM_LOCAL,
    SCHEMA_VERSION,
    LocalStore,
    LocalStoreError,
    payload_hash,
)

pytestmark = pytest.mark.integracao

PAYLOAD = {'value': 8080, 'type': 'int', 'description': 'porta'}


@pytest.fixture
def store(tmp_path):
    caminho = tmp_path / 'local_teste.json'
    s = LocalStore(str(caminho), threading.Lock(), 'teste')
    yield s
    s.close()


# ------------------------------------------------------------- schema


def test_schema_criado_na_primeira_abertura(store, tmp_path):
    """FIX-PM-16: o arquivo se identifica como próprio pelo cabeçalho."""
    assert store.schema_version == SCHEMA_VERSION
    dados = json.loads((tmp_path / 'local_teste.json').read_text('utf-8'))
    assert dados['meta']['1']['instance'] == 'teste'


def test_versao_futura_recusa_abrir(tmp_path):
    """
    FIX-PM-16: formato desconhecido é motivo para parar, não adivinhar.

    Abrir um arquivo mais novo do que a biblioteca entende é como se
    corrompe rascunho que o usuário ainda não sincronizou.
    """
    caminho = tmp_path / 'local_futuro.json'
    db = TinyDB(str(caminho))
    db.table('meta').insert({
        'schema_version': SCHEMA_VERSION + 1,
        'instance': 'teste',
    })
    db.close()

    with pytest.raises(LocalStoreError, match='mais nova'):
        LocalStore(str(caminho), threading.Lock(), 'teste')

    # E não pode deixar o arquivo travado: o handle já estava aberto
    # quando a validação falhou. No Windows, um TinyDB pendurado impede
    # até o usuário mexer no rascunho à mão. Renomear só funciona se
    # ninguém segurar o arquivo.
    caminho.rename(caminho.with_suffix('.movido'))


def test_versao_antiga_migra_sozinha(tmp_path):
    """FIX-PM-16: migração preguiçosa, sem script e sem janela."""
    caminho = tmp_path / 'local_velho.json'
    db = TinyDB(str(caminho))
    db.table('meta').insert({'schema_version': 0, 'instance': 'teste'})
    db.close()

    s = LocalStore(str(caminho), threading.Lock(), 'teste')
    try:
        assert s.schema_version == SCHEMA_VERSION
    finally:
        s.close()


# --------------------------------------------------------------- apps


def test_app_persiste_entre_aberturas(tmp_path):
    """
    FIX-PM-16: o dado sobrevive ao processo — que é o ponto do sidecar.

    Reabrir é o que separa 'gravou' de 'ficou na memória do mock'.
    """
    caminho = str(tmp_path / 'local.json')
    lock = threading.Lock()

    s1 = LocalStore(caminho, lock, 'teste')
    s1.upsert_app('financeiro', 'contas a pagar')
    s1.close()

    s2 = LocalStore(caminho, lock, 'teste')
    try:
        app = s2.get_app('financeiro')
        assert app['description'] == 'contas a pagar'
        assert app['origin'] == ORIGEM_LOCAL
    finally:
        s2.close()


def test_upsert_app_preserva_created_at(store):
    """FIX-PM-16: atualizar não é recriar."""
    primeiro = store.upsert_app('app', 'v1')
    segundo = store.upsert_app('app', 'v2')

    assert segundo['created_at'] == primeiro['created_at']
    assert segundo['updated_at'] >= primeiro['updated_at']
    assert segundo['description'] == 'v2'
    assert len(store.list_apps()) == 1


def test_delete_app_leva_os_parametros_junto(store):
    """
    FIX-PM-16: app removido não deixa parâmetro órfão.

    Órfão apareceria depois em `pendentes()` e a sincronização tentaria
    empurrar parâmetro de um app que ninguém mais conhece.
    """
    store.upsert_app('app')
    store.upsert_param('app', 'porta', PAYLOAD)
    store.upsert_app('outro')
    store.upsert_param('outro', 'porta', PAYLOAD)

    assert store.delete_app('app') is True
    assert store.get_app('app') is None
    assert store.list_params('app') == []
    assert len(store.list_params('outro')) == 1


def test_delete_app_inexistente_devolve_false(store):
    assert store.delete_app('nao-existe') is False


# ------------------------------------------------------------- params


def test_param_persiste_com_o_payload_do_put(tmp_path):
    """FIX-PM-16: guarda no formato exato que a sync vai enviar."""
    caminho = str(tmp_path / 'local.json')
    lock = threading.Lock()

    s1 = LocalStore(caminho, lock, 'teste')
    s1.upsert_param('app', 'porta', PAYLOAD)
    s1.close()

    s2 = LocalStore(caminho, lock, 'teste')
    try:
        registro = s2.get_param('app', 'porta')
        assert registro['payload'] == PAYLOAD
        assert registro['state'] == ESTADO_DRAFT
        assert registro['base_hash'] is None
    finally:
        s2.close()


@pytest.mark.parametrize('tipo', ['secret', 'user', 'users'])
def test_tipo_sensivel_e_recusado(store, tipo):
    """
    FIX-PM-16: guarda de última linha do modo local.

    O `encrypt` do envelope vive só no servidor, então o modo local não
    consegue produzir envelope válido — e gravar em claro violaria o
    invariante de que segredo nunca toca o disco.
    """
    with pytest.raises(LocalStoreError, match='servidor'):
        store.upsert_param('app', 'senha', {'value': 'x', 'type': tipo})

    assert store.get_param('app', 'senha') is None


def test_estado_invalido_e_recusado(store):
    with pytest.raises(LocalStoreError, match='Estado inválido'):
        store.upsert_param('app', 'porta', PAYLOAD, state='qualquer')


def test_upsert_param_preserva_base_hash(store):
    """
    FIX-PM-16: editar de novo não apaga a referência do que foi sincronizado.

    Perder o `base_hash` faria a sync tratar como conflito toda edição
    posterior à primeira sincronização.
    """
    store.upsert_param('app', 'porta', PAYLOAD)
    store.marcar('app', 'porta', ESTADO_SYNCED, base_hash='abc123')

    store.upsert_param('app', 'porta', {**PAYLOAD, 'value': 9090})

    registro = store.get_param('app', 'porta')
    assert registro['base_hash'] == 'abc123'
    assert registro['payload']['value'] == 9090


def test_delete_param_nao_toca_os_vizinhos(store):
    store.upsert_param('app', 'porta', PAYLOAD)
    store.upsert_param('app', 'host', {'value': 'x', 'type': 'string'})

    assert store.delete_param('app', 'porta') is True
    assert store.get_param('app', 'porta') is None
    assert store.get_param('app', 'host') is not None
    assert store.delete_param('app', 'porta') is False


# -------------------------------------------------- estados e pendências


def test_pendentes_traz_so_draft_e_dirty(store):
    """FIX-PM-16: 'o que falta subir' é consulta, não fila."""
    store.upsert_param('app', 'a', PAYLOAD, state=ESTADO_DRAFT)
    store.upsert_param('app', 'b', PAYLOAD, state=ESTADO_DIRTY)
    store.upsert_param('app', 'c', PAYLOAD, state=ESTADO_SYNCED)
    store.upsert_param('app', 'd', PAYLOAD, state=ESTADO_CONFLICT)
    store.upsert_param('app', 'e', PAYLOAD, state=ESTADO_REJECTED)

    assert [p['name'] for p in store.pendentes('app')] == ['a', 'b']


def test_pendentes_sem_app_varre_todos(store):
    store.upsert_param('um', 'a', PAYLOAD)
    store.upsert_param('dois', 'b', PAYLOAD)

    assert [(p['app'], p['name']) for p in store.pendentes()] == [
        ('dois', 'b'),
        ('um', 'a'),
    ]


def test_marcar_guarda_o_erro_do_servidor_verbatim(store):
    """
    FIX-PM-16: 422 traduzido perde a única informação útil.

    O `detail` do servidor é o que diz por que o parâmetro foi recusado;
    resumi-lo deixa o usuário sem saber o que corrigir.
    """
    detalhe = "Tamanho máximo excedido (30) no campo 'value'"
    store.upsert_param('app', 'porta', PAYLOAD)

    assert store.marcar(
        'app', 'porta', ESTADO_REJECTED, last_error=detalhe
    ) is True

    registro = store.get_param('app', 'porta')
    assert registro['state'] == ESTADO_REJECTED
    assert registro['last_error'] == detalhe


def test_marcar_param_inexistente_devolve_false(store):
    assert store.marcar('app', 'nada', ESTADO_SYNCED) is False


def test_upsert_limpa_erro_anterior(store):
    """Editar depois de uma recusa não pode manter o erro velho colado."""
    store.upsert_param('app', 'porta', PAYLOAD)
    store.marcar('app', 'porta', ESTADO_REJECTED, last_error='invalido')

    store.upsert_param('app', 'porta', {**PAYLOAD, 'value': 1})

    assert store.get_param('app', 'porta')['last_error'] is None


# ---------------------------------------------------------- base_hash


def test_payload_hash_ignora_ordem_das_chaves(store):
    """
    FIX-PM-16: ordem de chave não é conteúdo.

    Sem `sort_keys`, a mesma versão serializada de outro jeito geraria
    hash diferente e a sync veria conflito onde não há.
    """
    a = {'type': 'int', 'value': 1, 'description': 'x'}
    b = {'description': 'x', 'value': 1, 'type': 'int'}

    assert payload_hash(a) == payload_hash(b)
    assert payload_hash(a) != payload_hash({**a, 'value': 2})


# ------------------------------------------------- isolamento do cache


def test_sidecar_sobrevive_a_drop_table_no_arquivo_de_cache(tmp_path):
    """
    FIX-PM-16: é ESTE o motivo de o sidecar ser um arquivo separado.

    `manager.py` chama `drop_table(app)` em dois caminhos de recuperação
    — resposta da API com JSON inválido, e falha de leitura local. Num
    arquivo compartilhado, um erro de parsing de resposta da API apagaria
    rascunho ainda não sincronizado: perda de dado do usuário por uma
    falha sem relação nenhuma com ele.
    """
    cache_path = str(tmp_path / 'params_teste.json')
    side_path = str(tmp_path / 'local_teste.json')
    lock = threading.Lock()

    cache = TinyDB(cache_path)
    cache.table('app').insert({'timestamp': 1.0, 'params': {'x': 1}})

    store = LocalStore(side_path, lock, 'teste')
    try:
        store.upsert_app('app')
        store.upsert_param('app', 'porta', PAYLOAD)

        # O caminho de recuperação do manager, na íntegra.
        cache.drop_table('app')

        assert store.get_param('app', 'porta') is not None
        assert store.get_app('app') is not None
    finally:
        store.close()
        cache.close()


def test_cache_congelado_permanece_legivel_pelo_cliente_antigo(tmp_path):
    """
    FIX-PM-16: o formato que o 0.4.x lê não muda.

    Um cliente antigo faz `table(app).all()`, ordena por `timestamp` e
    pega `records[0]['params']`. O sidecar não aparece nesse caminho —
    ele nem sequer é aberto, porque o nome do arquivo de cache é fixo.
    """
    cache_path = str(tmp_path / 'params_teste.json')
    side_path = str(tmp_path / 'local_teste.json')

    cache = TinyDB(cache_path)
    cache.table('app').insert({'timestamp': 1.0, 'params': {'x': {'v': 1}}})

    store = LocalStore(side_path, threading.Lock(), 'teste')
    try:
        store.upsert_param('app', 'porta', PAYLOAD)

        registros = cache.table('app').all()
        registros.sort(key=lambda r: r.get('timestamp', 0), reverse=True)
        assert registros[0]['params'] == {'x': {'v': 1}}
        assert 'porta' not in registros[0]['params']
    finally:
        store.close()
        cache.close()
