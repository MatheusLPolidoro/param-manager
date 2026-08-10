"""
Superfície headless para o front (PyTauri).

Duas propriedades importam mais que o resto e são o motivo de este módulo
existir separado do `ParamManager`: a **cópia na fronteira** e o **erro
como dado**. Ambas têm teste explícito.

FIX-PM-21
"""

import pytest

from param_manager import api
from param_manager.manager import MODO_LOCAL, ParamManager

pytestmark = pytest.mark.integracao


@pytest.fixture
def sessao(tmp_path, monkeypatch):
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    monkeypatch.setenv('CHAVE_CUSTODIA_APP', '123456')
    ParamManager._instances = {}

    resposta = api.configure(
        instance_name='front',
        api_url='http://nao-chamado.invalid',
        local_db_path=str(tmp_path),
        mode=MODO_LOCAL,
    )
    assert resposta['ok'], resposta
    yield 'front'

    manager = ParamManager._instances.get('front')
    if manager is not None:
        manager._local_store.close()
        manager._db.close()
    ParamManager._instances = {}


def test_configure_devolve_o_modo(sessao):
    assert api.describe_session(sessao) == {
        'ok': True,
        'instance_name': 'front',
        'mode': MODO_LOCAL,
        'has_local_store': True,
    }


def test_ciclo_completo_pela_superficie_do_front(sessao):
    assert api.create_app('app', 'desc', instance_name=sessao)['ok']
    assert api.upsert_param(
        'app', 'porta', 8080, 'int', instance_name=sessao
    )['ok']

    lidos = api.get_all_params('app', instance_name=sessao)
    assert lidos['ok']
    assert lidos['params']['porta']['value'] == 8080

    assert api.get_param('app', 'porta', instance_name=sessao)['value'] == 8080
    assert api.list_apps(instance_name=sessao)['apps'][0]['name'] == 'app'

    assert api.delete_param('app', 'porta', instance_name=sessao)['ok']
    assert api.delete_app('app', instance_name=sessao)['ok']


def test_resposta_e_copia_e_nao_o_objeto_vivo(sessao):
    """
    FIX-PM-21: a razão de ser deste módulo.

    `get_all_params` do manager devolve, para tipos não sensíveis, o
    MESMO objeto guardado no cache. Atravessando IPC isso é corrida de
    dado durante a serialização. Aqui, mutar o que o front recebeu não
    pode alcançar nada de dentro.
    """
    api.upsert_param('app', 'porta', 8080, 'int', instance_name=sessao)

    primeira = api.get_all_params('app', instance_name=sessao)
    primeira['params']['porta']['value'] = 'contaminado'
    primeira['params']['injetado'] = {'value': 1, 'type': 'int'}

    segunda = api.get_all_params('app', instance_name=sessao)
    assert segunda['params']['porta']['value'] == 8080
    assert 'injetado' not in segunda['params']


def test_erro_vira_dado_e_nao_excecao(sessao):
    """
    FIX-PM-21: exceção atravessando a ponte de IPC vira stack trace.

    O front precisa da mensagem para mostrar, não de um traceback.
    """
    resposta = api.delete_param('app', 'inexistente', instance_name=sessao)

    assert resposta['ok'] is False
    assert resposta['error_type'] == 'LocalStoreError'
    assert 'não existe' in resposta['error']


def test_tipo_sensivel_falha_com_mensagem_util(sessao):
    """A mensagem é para ser mostrada como está, não traduzida."""
    resposta = api.upsert_param(
        'app', 'senha', 'x', 'secret', instance_name=sessao
    )

    assert resposta['ok'] is False
    assert 'servidor' in resposta['error']


def test_sync_status_nao_toca_a_rede(sessao):
    """
    FIX-PM-21: é o que alimenta o indicador de 'N alterações pendentes'.

    Se custasse uma requisição, o front não poderia consultá-lo com a
    frequência que um indicador exige. Não há mock de rede montado aqui:
    qualquer tentativa de sair falharia o teste.
    """
    api.upsert_param('app', 'a', 1, 'int', instance_name=sessao)
    api.upsert_param('app', 'b', 2, 'int', instance_name=sessao)

    status = api.sync_status(instance_name=sessao)

    assert status['ok']
    assert status['pending'] == 2
    assert status['rejected'] == 0
    assert status['conflict'] == 0


def test_catalogo_de_tipos_disponivel_sem_rede(sessao):
    resposta = api.type_catalog(instance_name=sessao)

    assert resposta['ok']
    assert 'int' in resposta['catalog']['types']


def test_sessao_nao_configurada_falha_dizendo_o_que_houve():
    """
    FIX-PM-21: errar o `instance_name` é engano comum num front.

    Sem esta guarda, `get_instance` construiria uma sessão nova com os
    defaults — sem URL, em modo remoto — e o front passaria a operar
    contra algo que ninguém configurou: leria vazio e falharia toda
    escrita com uma mensagem sobre rede, escondendo a causa real.
    """
    ParamManager._instances = {}

    resposta = api.sync_status(instance_name='nunca_configurada')

    assert resposta['ok'] is False
    assert resposta['error_type'] == 'LookupError'
    assert 'não foi configurada' in resposta['error']
    # E não pode ter criado nada de lado.
    assert ParamManager._instances == {}
