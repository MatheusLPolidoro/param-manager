"""
Handlers do front.

O que estes testes protegem, e que não é óbvio: **nenhum handler pode
levantar**. Uma exceção atravessando a ponte do PyTauri chega ao
JavaScript como stack trace, e a UI não tem o que fazer com isso. Todo
caminho de erro — sessão inexistente, corpo sem a chave esperada, tipo
errado — precisa virar `{'ok': False, ...}`.

O segundo, igualmente silencioso: a resposta precisa ser **serializável**.
Um `datetime` ou um `set` escapando aqui só falha na hora de atravessar o
IPC, longe da causa.

FIX-PM-22
"""

import json

import pytest

from param_manager.front import handlers, session
from param_manager.manager import MODO_LOCAL, ParamManager

# Comandos que a UI conhece. A lista é a superfície acordada: mexer nela é
# mexer no contrato com o JavaScript, e o teste existe para que isso seja
# uma decisão, não um efeito colateral.
COMANDOS_ESPERADOS = {
    'configure',
    'describe_session',
    'list_apps',
    'list_params',
    'get_all_params',
    'get_param',
    'validate_param',
    'create_app',
    'upsert_param',
    'delete_param',
    'delete_app',
    'sync_status',
    'sync_plan',
    'sync_apply',
    'refresh_type_catalog',
    'type_catalog',
    'ui_prefs_get',
    'ui_prefs_set',
    'ui_bootstrap',
}

# Handlers que não dependem de sessão configurada.
SEM_SESSAO = {'ui_prefs_get', 'ui_prefs_set', 'ui_bootstrap', 'configure'}

MAX_LENGTH_ESPERADO = 100


@pytest.fixture(autouse=True)
def prefs_isoladas(tmp_path, monkeypatch):
    """
    As preferências do front não podem tocar o diretório real do usuário.

    Sem isto, rodar a suíte reescreve o tema e o idioma de quem estiver
    desenvolvendo — e no CI escreve no home do contêiner.
    """
    monkeypatch.setattr(
        session, '_base_config', lambda: tmp_path / 'config'
    )


@pytest.fixture
def sem_sessao():
    ParamManager._instances = {}
    yield
    ParamManager._instances = {}


def test_a_superficie_e_exatamente_a_acordada():
    assert set(handlers.HANDLERS) == COMANDOS_ESPERADOS


@pytest.mark.parametrize('nome', sorted(COMANDOS_ESPERADOS - SEM_SESSAO))
def test_sem_sessao_devolve_erro_como_dado(nome, sem_sessao):
    """Sessão inexistente é `ok: false`, nunca `LookupError` escapando."""
    resposta = handlers.HANDLERS[nome]({})

    assert resposta['ok'] is False
    assert resposta['error']
    assert resposta['error_type']


@pytest.mark.parametrize('nome', sorted(COMANDOS_ESPERADOS))
def test_corpo_vazio_nunca_levanta(nome, sem_sessao):
    """
    Inclusive os que exigem campos: falta de chave vira dado.

    É o caminho de um front com defeito, e um front com defeito não pode
    derrubar o processo Python que segura a janela.
    """
    resposta = handlers.HANDLERS[nome]({})

    assert isinstance(resposta, dict)
    assert 'ok' in resposta


@pytest.mark.parametrize('nome', sorted(COMANDOS_ESPERADOS))
def test_corpo_nulo_e_tratado(nome, sem_sessao):
    """O `body` pode chegar `None` da ponte; não pode virar `AttributeError`."""
    assert isinstance(handlers.HANDLERS[nome](None), dict)


@pytest.mark.parametrize('nome', sorted(COMANDOS_ESPERADOS))
def test_resposta_e_serializavel(nome, sem_sessao):
    json.dumps(handlers.HANDLERS[nome]({}))


def test_campo_obrigatorio_ausente_nomeia_o_campo(sem_sessao):
    """
    `KeyError` é convertido, e o nome do campo sobrevive na mensagem.

    Sem isso o front recebe "erro" e ninguém sabe qual campo faltou.
    """
    resposta = handlers.HANDLERS['list_params']({})

    assert resposta['ok'] is False
    assert resposta['error_type'] == 'KeyError'
    assert 'app' in resposta['error']


def test_bootstrap_responde_sem_sessao_configurada(sem_sessao):
    """
    É a primeira chamada da UI e acontece antes de qualquer `configure`.

    Se ela dependesse de sessão, o app abriria numa tela de erro em vez
    da tela de configuração.
    """
    resposta = handlers.HANDLERS['ui_bootstrap']({})

    assert resposta['ok'] is True
    assert resposta['language'] in ('pt-BR', 'en')
    assert resposta['languages']
    assert resposta['front_version']


def test_prefs_guardam_e_devolvem():
    handlers.HANDLERS['ui_prefs_set']({'theme': 'dark'})
    resposta = handlers.HANDLERS['ui_prefs_get']({})

    assert resposta['prefs']['theme'] == 'dark'


def test_prefs_ignoram_chave_desconhecida():
    """
    Front novo contra Python velho não pode gravar lixo no arquivo.

    Só as chaves conhecidas entram; o resto é descartado em silêncio, que
    é o comportamento certo para preferência de interface.
    """
    handlers.HANDLERS['ui_prefs_set']({'inventada': 1, 'theme': 'light'})
    prefs = handlers.HANDLERS['ui_prefs_get']({})['prefs']

    assert 'inventada' not in prefs
    assert prefs['theme'] == 'light'


def test_tema_invalido_cai_no_padrao():
    handlers.HANDLERS['ui_prefs_set']({'theme': 'neon'})

    assert handlers.HANDLERS['ui_prefs_get']({})['prefs']['theme'] == 'system'


# ------------------------------------------------------------- integração


@pytest.fixture
def sessao(tmp_path, monkeypatch):
    """Sessão local de verdade, com sidecar em disco."""
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    monkeypatch.setenv('CHAVE_CUSTODIA_APP', '123456')
    ParamManager._instances = {}

    resposta = handlers.HANDLERS['configure']({
        'instance_name': 'front',
        'api_url': 'http://nao-chamado.invalid',
        'local_db_path': str(tmp_path),
        'mode': MODO_LOCAL,
    })
    assert resposta['ok'], resposta
    yield 'front'

    manager = ParamManager._instances.get('front')
    if manager is not None:
        manager._local_store.close()
        manager._db.close()
    ParamManager._instances = {}


@pytest.mark.integracao
def test_ciclo_pela_camada_de_handlers(sessao):
    assert handlers.HANDLERS['create_app']({
        'instance_name': sessao, 'name': 'app', 'description': 'desc',
    })['ok']

    assert handlers.HANDLERS['upsert_param']({
        'instance_name': sessao,
        'app': 'app',
        'name': 'porta',
        'value': 8080,
        'param_type': 'int',
        'description': 'porta http',
    })['ok']

    listagem = handlers.HANDLERS['list_params']({
        'instance_name': sessao, 'app': 'app',
    })
    assert listagem['ok']
    assert listagem['params'][0]['name'] == 'porta'
    assert listagem['params'][0]['type'] == 'int'
    assert listagem['params'][0]['state'] == 'draft'

    assert handlers.HANDLERS['get_param']({
        'instance_name': sessao, 'app': 'app', 'name': 'porta',
    })['value'] == 8080

    assert handlers.HANDLERS['delete_param']({
        'instance_name': sessao, 'app': 'app', 'name': 'porta',
    })['ok']


@pytest.mark.integracao
def test_listagem_nunca_traz_o_valor(sessao):
    """
    A tabela é metadado.

    Trazer o payload aqui significaria envelope de `secret` atravessando o
    IPC a cada redesenho de linha — e é para evitar isso que
    `api.list_params` existe em vez de o front ler o store direto.
    """
    handlers.HANDLERS['create_app']({'instance_name': sessao, 'name': 'app'})
    handlers.HANDLERS['upsert_param']({
        'instance_name': sessao,
        'app': 'app',
        'name': 'senha_do_banco',
        'value': 'nao-deve-aparecer',
        'param_type': 'string',
    })

    listagem = handlers.HANDLERS['list_params']({
        'instance_name': sessao, 'app': 'app',
    })

    serializado = json.dumps(listagem)
    assert 'nao-deve-aparecer' not in serializado
    assert 'payload' not in serializado


@pytest.mark.integracao
def test_listagem_preserva_o_metadado_que_o_formulario_reenvia(sessao):
    """
    FIX-PM-23: editar o valor apagava `user_editable` e os limites.

    A listagem projetava só um punhado de campos conhecidos. O formulário
    de detalhe lê dela para se preencher, e em modo local o `upsert`
    **substitui o payload inteiro** — então tudo que a projeção tivesse
    esquecido voltava vazio no PUT seguinte e sumia do disco.

    Nunca foi visível: o parâmetro continuava lá, com o valor certo, sem
    o limite que alguém havia definido.
    """
    handlers.HANDLERS['create_app']({'instance_name': sessao, 'name': 'app'})
    handlers.HANDLERS['upsert_param']({
        'instance_name': sessao,
        'app': 'app',
        'name': 'p',
        'value': 'x',
        'param_type': 'string',
        'description': 'desc',
        'user_editable': True,
        'max_length': 100,
    })

    resumo = handlers.HANDLERS['list_params']({
        'instance_name': sessao, 'app': 'app',
    })['params'][0]

    assert resumo['user_editable'] is True
    assert resumo['max_length'] == MAX_LENGTH_ESPERADO
    assert resumo['description'] == 'desc'
    # a única omissão deliberada
    assert 'value' not in resumo


@pytest.mark.integracao
def test_listagem_local_carimba_a_data_do_sidecar(sessao):
    """
    FIX-PM-24: `updated_at` explícito apagava a data vinda do payload.

    A chave explícita ficava DEPOIS do espalhamento do metadado, então
    `None` sobrescrevia o que o documento trazia — e em modo remoto,
    onde a data vem do servidor dentro do próprio payload, a coluna
    "atualizado" saía como travessão para todos os parâmetros. O
    travessão também é o valor legítimo de "sem data", e por isso o
    defeito passava por comportamento.
    """
    handlers.HANDLERS['create_app']({'instance_name': sessao, 'name': 'app'})
    handlers.HANDLERS['upsert_param']({
        'instance_name': sessao, 'app': 'app', 'name': 'p',
        'value': 1, 'param_type': 'int',
    })

    resumo = handlers.HANDLERS['list_params']({
        'instance_name': sessao, 'app': 'app',
    })['params'][0]

    assert resumo['updated_at'] is not None


@pytest.mark.integracao
def test_validate_param_avisa_sem_gravar(sessao):
    """
    O aviso precisa chegar ANTES da gravação, e sem gravar nada.

    Antes disto a validação existia e só virava `logger.warning`, no
    caminho de escrita e só no modo local — quem operava por uma tela
    descobria o limite no fim de uma sincronização inteira.
    """
    resposta = handlers.HANDLERS['validate_param']({
        'instance_name': sessao,
        'value': 'x' * 40,
        'param_type': 'string',
    })

    assert resposta['ok'] is True
    assert resposta['warnings'], 'string de 40 passa do max_length padrão 30'

    # nada foi criado pelo caminho de validação
    assert handlers.HANDLERS['list_apps']({'instance_name': sessao})['apps'] == []


@pytest.mark.integracao
def test_validate_param_aceita_o_que_esta_dentro_do_limite(sessao):
    resposta = handlers.HANDLERS['validate_param']({
        'instance_name': sessao,
        'value': 'curto',
        'param_type': 'string',
    })

    assert resposta['warnings'] == []


@pytest.mark.integracao
def test_tipo_sensivel_em_local_devolve_a_mensagem_da_lib(sessao):
    """
    A recusa vem da lib com a explicação pronta; o handler não a reescreve.

    O front mostra o texto como veio — traduzi-lo aqui produziria duas
    versões da mesma regra.
    """
    handlers.HANDLERS['create_app']({'instance_name': sessao, 'name': 'app'})
    resposta = handlers.HANDLERS['upsert_param']({
        'instance_name': sessao,
        'app': 'app',
        'name': 'senha',
        'value': 'x',
        'param_type': 'secret',
    })

    assert resposta['ok'] is False
    assert resposta['error']


@pytest.mark.integracao
def test_configure_guarda_a_instancia_nas_preferencias(sessao):
    assert session.carregar()['last_instance'] == 'front'
