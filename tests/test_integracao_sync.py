"""
Sincronização de ponta a ponta: plano, aplicação e os caminhos de recusa.

Aqui a rede é mockada, mas o arquivo é REAL — o que se está aferindo é a
reconciliação do estado local depois de cada resposta do servidor, e isso
o mock de TinyDB esconderia.

FIX-PM-20
"""

import pytest

from param_manager.local_store import (
    ESTADO_DRAFT,
    ESTADO_REJECTED,
    ESTADO_SYNCED,
    LocalStoreError,
    payload_hash,
)
from param_manager.manager import MODO_LOCAL, MODO_REMOTO, ParamManager
from param_manager.sync import ACAO_CONFLITO

pytestmark = pytest.mark.integracao

API = 'http://sync-teste.invalid'
DOC_SERVIDOR = {'value': 1, 'type': 'int', 'description': None}


@pytest.fixture
def pm(tmp_path, monkeypatch, requests_mock):
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    monkeypatch.setenv('CHAVE_CUSTODIA_APP', '123456')
    ParamManager._instances = {}

    requests_mock.post(
        f'{API}/auth/token',
        json={'access_token': 'tok', 'refresh_token': 'ref'},
    )

    instancia = ParamManager(
        api_url=API,
        local_db_path=str(tmp_path),
        username='u',
        password='p',
        instance_name='sync_teste',
        mode=MODO_LOCAL,
    )
    yield instancia, requests_mock
    instancia._local_store.close()
    instancia._db.close()
    ParamManager._instances = {}


def _sem_apps(rm):
    rm.get(f'{API}/parameters/apps/', json={'apps': []})


# ------------------------------------------------------------ guardas


def test_sync_exige_modo_local(tmp_path, monkeypatch):
    """Em modo remoto não há rascunho para sincronizar."""
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    ParamManager._instances = {}
    remoto = ParamManager(
        api_url=API,
        local_db_path=str(tmp_path),
        instance_name='remoto',
        mode=MODO_REMOTO,
    )
    try:
        with pytest.raises(LocalStoreError, match='só existe no modo local'):
            remoto.sync_plan()
        with pytest.raises(LocalStoreError, match='só existe no modo local'):
            remoto.sync_apply({})
    finally:
        remoto._db.close()
        ParamManager._instances = {}


# --------------------------------------------------------------- plano


def test_plano_nao_grava_nada(pm):
    """
    FIX-PM-20: a fase 1 é só cálculo.

    É o que permite mostrar um diff antes de tocar no servidor.
    """
    manager, rm = pm
    _sem_apps(rm)
    manager.upsert_params('app', 'porta', value=1, param_type='int')

    plano = manager.sync_plan()

    assert plano['apps_to_create'] == ['app']
    assert plano['summary']['create'] == 1
    # Estado intocado: nada foi empurrado.
    assert (
        manager._local_store.get_param('app', 'porta')['state']
        == ESTADO_DRAFT
    )


# ---------------------------------------------------- caminho feliz


def test_app_e_criado_antes_dos_parametros(pm):
    """
    FIX-PM-20: PUT em app inexistente responde 404.

    A ordem é parte do plano, e este teste confere a ORDEM real das
    requisições, não só o resultado final.
    """
    manager, rm = pm
    _sem_apps(rm)
    rm.post(
        f'{API}/parameters/apps/',
        json={'message': 'ok', 'app': 'app'},
        status_code=201,
    )
    rm.put(
        f'{API}/parameters/apps/app/params/',
        json={'app': 'app', 'params': {'porta': DOC_SERVIDOR}},
    )
    manager.upsert_params('app', 'porta', value=1, param_type='int')

    resultado = manager.sync_apply(manager.sync_plan())

    assert resultado['apps_created'] == ['app']
    assert resultado['synced'] == [{'app': 'app', 'name': 'porta'}]

    caminhos = [r.path for r in rm.request_history]
    assert caminhos.index('/parameters/apps/') < caminhos.index(
        '/parameters/apps/app/params/'
    )


def test_base_hash_nasce_da_resposta_canonica_do_servidor(pm):
    """
    FIX-PM-20: a versão do servidor é a autoritativa depois da sincronia.

    Guardar o payload do cliente como base faria o próximo plano ver
    conflito onde não há — os dois lados têm formas diferentes.
    """
    manager, rm = pm
    _sem_apps(rm)
    rm.post(
        f'{API}/parameters/apps/',
        json={'message': 'ok', 'app': 'app'},
        status_code=201,
    )
    rm.put(
        f'{API}/parameters/apps/app/params/',
        json={'app': 'app', 'params': {'porta': DOC_SERVIDOR}},
    )
    manager.upsert_params('app', 'porta', value=1, param_type='int')

    manager.sync_apply(manager.sync_plan())

    registro = manager._local_store.get_param('app', 'porta')
    assert registro['state'] == ESTADO_SYNCED
    assert registro['base_hash'] == payload_hash(DOC_SERVIDOR)


# ------------------------------------------------ caminhos de recusa


def test_422_marca_rejeitado_e_guarda_o_detalhe_verbatim(pm):
    """
    FIX-PM-20: o parâmetro PERMANECE no store.

    Descartá-lo apagaria o trabalho de quem o escreveu, e resumir o erro
    tiraria a única informação que diz o que corrigir.
    """
    manager, rm = pm
    rm.get(f'{API}/parameters/apps/', json={'apps': [{'name': 'app'}]})
    rm.get(f'{API}/parameters/apps/app/params/', json={'params': {}})
    detalhe = 'Tamanho máximo excedido (30)'
    rm.put(
        f'{API}/parameters/apps/app/params/', text=detalhe, status_code=422
    )
    manager.upsert_params('app', 'porta', value=1, param_type='int')

    resultado = manager.sync_apply(manager.sync_plan())

    assert resultado['rejected'][0]['name'] == 'porta'
    registro = manager._local_store.get_param('app', 'porta')
    assert registro['state'] == ESTADO_REJECTED
    assert registro['last_error'] == detalhe
    assert registro['payload'] is not None


def test_403_e_credencial_e_nao_dado(pm):
    """
    FIX-PM-20: 403 não pode virar `rejected`.

    Marcar como rejeitado faria parecer que o valor está errado, quando o
    que falta é permissão — e o parâmetro deixaria de ser tentado de novo
    depois de trocar a credencial.
    """
    manager, rm = pm
    rm.get(f'{API}/parameters/apps/', json={'apps': [{'name': 'app'}]})
    rm.get(f'{API}/parameters/apps/app/params/', json={'params': {}})
    rm.put(
        f'{API}/parameters/apps/app/params/',
        text='sem permissão',
        status_code=403,
    )
    manager.upsert_params('app', 'porta', value=1, param_type='int')

    resultado = manager.sync_apply(manager.sync_plan())

    assert resultado['forbidden'][0]['name'] == 'porta'
    assert resultado['rejected'] == []
    # Continua pendente: tentar de novo com a credencial certa resolve.
    assert (
        manager._local_store.get_param('app', 'porta')['state']
        == ESTADO_DRAFT
    )


def test_uma_recusa_nao_interrompe_as_demais(pm):
    """
    FIX-PM-20: sincronização é por parâmetro, então segue depois de um 422.

    Abortar tudo por causa de um parâmetro inválido deixaria o resto do
    trabalho parado sem motivo.
    """
    manager, rm = pm
    rm.get(f'{API}/parameters/apps/', json={'apps': [{'name': 'app'}]})
    rm.get(f'{API}/parameters/apps/app/params/', json={'params': {}})
    rm.put(
        f'{API}/parameters/apps/app/params/',
        [
            {'text': 'invalido', 'status_code': 422},
            {
                'json': {'app': 'app', 'params': {'b': DOC_SERVIDOR}},
                'status_code': 200,
            },
        ],
    )
    manager.upsert_params('app', 'a', value=1, param_type='int')
    manager.upsert_params('app', 'b', value=2, param_type='int')

    resultado = manager.sync_apply(manager.sync_plan())

    assert len(resultado['rejected']) == 1
    assert len(resultado['synced']) == 1


# ------------------------------------------------------------ conflito


def test_conflito_nao_e_empurrado(pm):
    """
    FIX-PM-20: 'nunca decidir sozinho', na prática.

    O parâmetro existe nos dois lados e nunca foi sincronizado por aqui,
    então não há como saber qual versão é a mais nova. Nenhum PUT sai.
    """
    manager, rm = pm
    rm.get(f'{API}/parameters/apps/', json={'apps': [{'name': 'app'}]})
    rm.get(
        f'{API}/parameters/apps/app/params/',
        json={'params': {'porta': DOC_SERVIDOR}},
    )
    manager.upsert_params('app', 'porta', value=99, param_type='int')

    plano = manager.sync_plan()
    assert plano['summary']['conflict'] == 1
    assert plano['params'][0]['action'] == ACAO_CONFLITO

    resultado = manager.sync_apply(plano)

    assert resultado['synced'] == []
    assert resultado['skipped_conflicts'][0]['name'] == 'porta'
    assert not any(r.method == 'PUT' for r in rm.request_history)
