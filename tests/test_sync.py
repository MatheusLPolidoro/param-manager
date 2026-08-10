"""
Planejamento da sincronização: classificação e montagem do plano.

Puro, sem rede e sem arquivo — que é o ponto de ter separado o
planejamento da orquestração. A regra de conflito é a parte que mais
importa acertar e a que mais barato sai testar assim.

FIX-PM-19
"""

from param_manager.local_store import payload_hash
from param_manager.sync import (
    ACAO_ATUALIZAR,
    ACAO_CONFLITO,
    ACAO_CRIAR,
    classificar_param,
    itens_aplicaveis,
    montar_plano,
)

DOC_REMOTO = {'value': 1, 'type': 'int', 'description': 'porta'}


def _local(base_hash=None, app='app', name='porta', value=1):
    return {
        'app': app,
        'name': name,
        'payload': {'value': value, 'type': 'int'},
        'base_hash': base_hash,
        'state': 'dirty',
    }


# --------------------------------------------------------- classificação


def test_ausente_no_servidor_e_criacao():
    acao, motivo = classificar_param(_local(), None)

    assert acao == ACAO_CRIAR
    assert 'não existe no servidor' in motivo


def test_servidor_inalterado_desde_a_ultima_sincronia_e_atualizacao():
    """
    FIX-PM-19: o `base_hash` bate, logo ninguém mexeu lá desde então.

    É o único caso em que empurrar é seguro sem perguntar nada.
    """
    registro = _local(base_hash=payload_hash(DOC_REMOTO))

    acao, _ = classificar_param(registro, DOC_REMOTO)

    assert acao == ACAO_ATUALIZAR


def test_servidor_mudou_depois_da_ultima_sincronia_e_conflito():
    """FIX-PM-19: empurrar aqui apagaria o que outra pessoa escreveu."""
    registro = _local(base_hash=payload_hash(DOC_REMOTO))
    remoto_novo = {**DOC_REMOTO, 'value': 99}

    acao, motivo = classificar_param(registro, remoto_novo)

    assert acao == ACAO_CONFLITO
    assert 'servidor mudou' in motivo


def test_existe_nos_dois_e_nunca_sincronizou_e_conflito():
    """
    FIX-PM-19: sem base de comparação, não há como saber quem é mais novo.

    Tratar como atualização apagaria o valor do servidor; tratar como
    criação faria o servidor recusar ou sobrescrever. Conflito é a única
    resposta honesta.
    """
    acao, motivo = classificar_param(_local(base_hash=None), DOC_REMOTO)

    assert acao == ACAO_CONFLITO
    assert 'nunca foi sincronizado' in motivo


def test_base_hash_e_sobre_o_documento_do_servidor():
    """
    FIX-PM-19: a comparação é servidor-contra-servidor.

    O payload local e o documento do servidor têm formas diferentes — o
    servidor devolve metadados completos, o payload é o subconjunto do
    PUT. Comparar cruzado nunca casaria e TUDO viraria conflito.
    """
    registro = _local(base_hash=payload_hash(registro_payload := {
        'value': 1,
        'type': 'int',
    }))
    assert registro_payload  # o payload local, propositalmente diferente

    acao, _ = classificar_param(registro, DOC_REMOTO)

    assert acao == ACAO_CONFLITO


# ---------------------------------------------------------------- plano


def test_plano_lista_os_apps_que_faltam_no_servidor():
    """
    FIX-PM-19: app antes de parâmetro, sempre.

    PUT em app inexistente responde 404, então a ordem é parte do plano
    e não detalhe de quem aplica.
    """
    pendentes = [_local(app='novo'), _local(app='ja_existe')]

    plano = montar_plano(pendentes, {}, apps_remotos={'ja_existe'})

    assert plano['apps_to_create'] == ['novo']


def test_plano_conta_cada_acao():
    pendentes = [
        _local(app='a', name='cria'),
        _local(app='a', name='atualiza', base_hash=payload_hash(DOC_REMOTO)),
        _local(app='a', name='conflita', base_hash='outro'),
    ]
    remotos = {
        'a': {'atualiza': DOC_REMOTO, 'conflita': DOC_REMOTO},
    }

    plano = montar_plano(pendentes, remotos, apps_remotos={'a'})

    assert plano['summary'] == {'create': 1, 'update': 1, 'conflict': 1}


def test_plano_carrega_os_dois_lados_para_a_tela_de_diff():
    """O front precisa mostrar local e remoto lado a lado."""
    pendentes = [_local(base_hash='velho')]

    plano = montar_plano(pendentes, {'app': {'porta': DOC_REMOTO}}, {'app'})
    item = plano['params'][0]

    assert item['local'] == {'value': 1, 'type': 'int'}
    assert item['remote'] == DOC_REMOTO
    assert item['reason']


def test_conflito_nunca_entra_no_que_sera_aplicado():
    """
    FIX-PM-19: a regra que sustenta 'nunca decidir sozinho'.

    Quem quiser forçar reescreve a ação do item para `update` antes de
    aplicar — e aí a escolha é explícita e rastreável.
    """
    plano = {
        'params': [
            {'app': 'a', 'name': 'x', 'action': ACAO_CRIAR},
            {'app': 'a', 'name': 'y', 'action': ACAO_ATUALIZAR},
            {'app': 'a', 'name': 'z', 'action': ACAO_CONFLITO},
        ]
    }

    nomes = [i['name'] for i in itens_aplicaveis(plano)]

    assert nomes == ['x', 'y']


def test_plano_vazio_nao_quebra():
    plano = montar_plano([], {}, set())

    assert plano['params'] == []
    assert plano['apps_to_create'] == []
    assert itens_aplicaveis(plano) == []
