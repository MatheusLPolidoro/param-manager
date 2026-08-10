"""
Modo `local`: autoria sem servidor, direto no sidecar.

Integração contra arquivo real e sem `requests_mock`: o ponto do modo
local é que **nenhuma requisição acontece**, e a forma mais honesta de
afirmar isso é não ter mock de rede montado. Se algum caminho tentar
sair para a rede, o teste falha por conta própria.

FIX-PM-17
"""

import pytest

from param_manager.local_store import (
    ESTADO_DIRTY,
    ESTADO_DRAFT,
    LocalStoreError,
)
from param_manager.manager import MODO_LOCAL, MODO_REMOTO, ParamManager

pytestmark = pytest.mark.integracao

PORTA = {'value': 8080, 'type': 'int'}


@pytest.fixture
def pm_local(tmp_path, monkeypatch):
    """Instância em modo local, com o sidecar num diretório temporário."""
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    monkeypatch.setenv('CHAVE_CUSTODIA_APP', '123456')
    ParamManager._instances = {}

    pm = ParamManager(
        api_url='http://nao-deve-ser-chamado.invalid',
        local_db_path=str(tmp_path),
        instance_name='local_teste',
        mode=MODO_LOCAL,
    )
    yield pm
    pm._local_store.close()
    pm._db.close()
    ParamManager._instances = {}


# ----------------------------------------------------- resolução do modo


def test_default_continua_remoto(tmp_path, monkeypatch):
    """
    FIX-PM-17: quem não pede nada não percebe que este eixo existe.

    É o que sustenta a compatibilidade: o modo é opt-in e o default
    reproduz o comportamento publicado.
    """
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    ParamManager._instances = {}
    pm = ParamManager(
        api_url='http://x.invalid',
        local_db_path=str(tmp_path),
        instance_name='padrao',
    )
    try:
        assert pm.mode == MODO_REMOTO
        # Sem sidecar aberto: quem roda remoto não paga o segundo handle
        # nem ganha um arquivo a mais no disco.
        assert pm._local_store is None
        # list(): glob devolve gerador, e gerador é sempre truthy — a
        # asserção passaria com qualquer resultado.
        sidecars = list(
            (tmp_path / 'param_manager' / 'padrao').glob('local_*')
        )
        assert sidecars == []
    finally:
        pm._db.close()
        ParamManager._instances = {}


def test_env_global_liga_o_modo_local(tmp_path, monkeypatch):
    monkeypatch.setenv('PARAM_MANAGER_MODE', 'local')
    ParamManager._instances = {}
    pm = ParamManager(
        api_url='http://x.invalid',
        local_db_path=str(tmp_path),
        instance_name='porenv',
    )
    try:
        assert pm.mode == MODO_LOCAL
    finally:
        pm._local_store.close()
        pm._db.close()
        ParamManager._instances = {}


def test_env_prefixada_vence_a_global(tmp_path, monkeypatch):
    """FIX-PM-17: mesma precedência de três degraus do resto da lib."""
    monkeypatch.setenv('PARAM_MANAGER_MODE', 'remote')
    monkeypatch.setenv('PREFIXADA_PARAM_MANAGER_MODE', 'local')
    ParamManager._instances = {}
    pm = ParamManager(
        api_url='http://x.invalid',
        local_db_path=str(tmp_path),
        instance_name='prefixada',
    )
    try:
        assert pm.mode == MODO_LOCAL
    finally:
        pm._local_store.close()
        pm._db.close()
        ParamManager._instances = {}


def test_argumento_vence_as_duas_envs(tmp_path, monkeypatch):
    monkeypatch.setenv('PARAM_MANAGER_MODE', 'local')
    monkeypatch.setenv('ARG_PARAM_MANAGER_MODE', 'local')
    ParamManager._instances = {}
    pm = ParamManager(
        api_url='http://x.invalid',
        local_db_path=str(tmp_path),
        instance_name='arg',
        mode=MODO_REMOTO,
    )
    try:
        assert pm.mode == MODO_REMOTO
    finally:
        pm._db.close()
        ParamManager._instances = {}


def test_modo_invalido_cai_para_remoto(tmp_path, monkeypatch, caplog):
    """
    FIX-PM-17: valor irreconhecível não derruba a construção, e cai para
    o lado SEGURO.

    Cair para `local` deixaria a aplicação lendo rascunho sem que
    ninguém tivesse pedido.
    """
    monkeypatch.setenv('PARAM_MANAGER_MODE', 'lokal')
    ParamManager._instances = {}
    pm = ParamManager(
        api_url='http://x.invalid',
        local_db_path=str(tmp_path),
        instance_name='invalido',
    )
    try:
        assert pm.mode == MODO_REMOTO
        assert 'não reconhecido' in caplog.text
    finally:
        pm._db.close()
        ParamManager._instances = {}


def test_sem_url_nao_liga_modo_local(tmp_path, monkeypatch):
    """
    FIX-PM-17: veto registrado.

    Hoje, sem URL, a leitura falha para o banco local e devolve `{}`.
    Transformar isso em "entra em local e aceita escrita" mudaria o
    comportamento de quem roda sem URL por engano.
    """
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    for chave in ('API_PARAMS_URL', 'API_URL'):
        monkeypatch.setenv(chave, '')
    ParamManager._instances = {}
    pm = ParamManager(
        local_db_path=str(tmp_path), instance_name='sem_url'
    )
    try:
        assert pm.mode == MODO_REMOTO
    finally:
        pm._db.close()
        ParamManager._instances = {}


def test_get_instance_aceita_o_modo(tmp_path, monkeypatch):
    """
    FIX-PM-17: `get_instance` é o ponto de entrada que a documentação
    ensina, então o modo precisa chegar por ele.

    Passa pelo `**kwargs` — e é por isso que `mode` é keyword-only: um
    posicional novo antes da posição 6 registraria a instância no slot
    errado do multiton.
    """
    monkeypatch.delenv('PARAM_MANAGER_MODE', raising=False)
    ParamManager._instances = {}
    pm = ParamManager.get_instance(
        instance_name='via_get_instance',
        api_url='http://x.invalid',
        local_db_path=str(tmp_path),
        mode=MODO_LOCAL,
    )
    try:
        assert pm.mode == MODO_LOCAL
        assert pm._instance_name == 'via_get_instance'
    finally:
        pm._local_store.close()
        pm._db.close()
        ParamManager._instances = {}


# -------------------------------------------------------------- escrita


def test_ciclo_de_vida_completo_sem_servidor(pm_local):
    """FIX-PM-17: criar app, gravar, ler e apagar, tudo offline."""
    criado = pm_local.create_app('financeiro', 'contas')
    assert set(criado) == {'message', 'app'}
    assert criado['app']['name'] == 'financeiro'

    resposta = pm_local.upsert_params(
        'financeiro', 'porta', value=8080, param_type='int'
    )
    # Mesma forma de topo do PUT do servidor.
    assert set(resposta) == {'app', 'params'}
    assert resposta['params']['porta']['value'] == 8080

    assert pm_local.get_param('financeiro', 'porta') == 8080
    assert pm_local.get_all_params('financeiro')['porta']['value'] == 8080

    assert 'message' in pm_local.delete_param('financeiro', 'porta')
    assert pm_local.get_param('financeiro', 'porta') is None

    assert 'message' in pm_local.delete_app('financeiro')
    assert pm_local.list_apps()['apps'] == []


def test_upsert_cria_o_app_que_faltava(pm_local):
    """
    FIX-PM-17: gravar parâmetro em app inexistente é caminho comum aqui.

    Exigir create_app antes seria atrito puro no desenvolvimento local.
    """
    pm_local.upsert_params('novo', 'porta', value=1, param_type='int')

    assert pm_local._local_store.get_app('novo') is not None


def test_primeira_escrita_e_draft_e_a_seguinte_continua_draft(pm_local):
    """Enquanto nunca sincronizou, não há base para comparar."""
    pm_local.upsert_params('app', 'porta', value=1, param_type='int')
    assert (
        pm_local._local_store.get_param('app', 'porta')['state']
        == ESTADO_DRAFT
    )

    pm_local.upsert_params('app', 'porta', value=2, param_type='int')
    assert (
        pm_local._local_store.get_param('app', 'porta')['state']
        == ESTADO_DRAFT
    )


def test_edicao_do_que_ja_sincronizou_vira_dirty(pm_local):
    """
    FIX-PM-17: `dirty` separa 'criei agora' de 'mexi no que o servidor
    já conhece' — e é essa diferença que a sync usa para saber se
    precisa conferir divergência antes de empurrar.
    """
    pm_local.upsert_params('app', 'porta', value=1, param_type='int')
    pm_local._local_store.marcar(
        'app', 'porta', 'synced', base_hash='abc'
    )

    pm_local.upsert_params('app', 'porta', value=2, param_type='int')

    assert (
        pm_local._local_store.get_param('app', 'porta')['state']
        == ESTADO_DIRTY
    )


@pytest.mark.parametrize('tipo', ['secret', 'user', 'users'])
def test_tipo_sensivel_e_recusado_com_mensagem_clara(pm_local, tipo):
    """
    FIX-PM-17: o `encrypt` do envelope vive só no servidor.

    LocalStoreError herda de Exception, então quem já capturava
    genericamente as escritas continua capturando.
    """
    with pytest.raises(LocalStoreError, match='servidor'):
        pm_local.upsert_params(
            'app', 'senha', value='x', param_type=tipo
        )

    assert pm_local.get_param('app', 'senha') is None


def test_apagar_o_que_nao_existe_levanta(pm_local):
    """Espelha o servidor, que responde erro e faz o cliente levantar."""
    with pytest.raises(LocalStoreError):
        pm_local.delete_param('app', 'nada')
    with pytest.raises(LocalStoreError):
        pm_local.delete_app('nada')


# -------------------------------------------------------------- leitura


def test_aviso_de_limite_nao_impede_a_gravacao(pm_local, caplog):
    """
    FIX-PM-17: advisory é conselho, e conselho não bloqueia.

    Uma string de 40 caracteres passa do `max_length` padrão de 30 e
    seria recusada pelo servidor. Aqui ela é gravada, com aviso — quem
    decide é a sincronização, e o desenvolvedor fica sabendo antes de
    chegar lá.
    """
    pm_local.upsert_params(
        'app', 'nome', value='x' * 40, param_type='string'
    )

    assert 'max_length' in caplog.text
    assert pm_local.get_param('app', 'nome') == 'x' * 40


def test_catalogo_guardado_no_sidecar_vence_o_embarcado(pm_local):
    """
    FIX-PM-17: catálogo é dado, então tipo novo não exige release.

    Guardado o catálogo do servidor, um tipo que o piso embarcado não
    conhece para de gerar aviso.
    """
    from param_manager.type_catalog import CATALOGO_EMBARCADO

    pm_local._local_store.guardar_catalogo({
        **CATALOGO_EMBARCADO,
        'types': [*CATALOGO_EMBARCADO['types'], 'duration'],
    })

    assert 'duration' in pm_local._type_catalog()['types']


def test_leitura_de_app_desconhecido_nao_explode(pm_local):
    """
    FIX-PM-17: o contrato de leitura vale igual no modo local.

    `get_param` devolve valor ou None; `get_all_params`, um dicionário.
    Nenhum dos dois levanta por ausência.
    """
    assert pm_local.get_param('inexistente', 'x') is None
    assert pm_local.get_all_params('inexistente') == {}


def test_leitura_local_nao_usa_o_cache_do_processo(pm_local):
    """
    FIX-PM-17: o arquivo é local e quem edita acabou de mudá-lo.

    Cachear aqui só criaria a chance de servir ao próprio usuário o
    valor anterior ao que ele acabou de gravar.
    """
    pm_local.upsert_params('app', 'porta', value=1, param_type='int')
    assert pm_local.get_param('app', 'porta') == 1

    # Escreve por baixo, direto no store, sem passar pelo manager.
    pm_local._local_store.upsert_param(
        'app', 'porta', {'value': 99, 'type': 'int'}
    )

    assert pm_local.get_param('app', 'porta') == 99
