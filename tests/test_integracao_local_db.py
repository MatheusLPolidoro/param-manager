"""
Testes de integração contra um arquivo TinyDB real.

A suíte unitária troca o TinyDB por `MagicMock`, o que introduz um
comportamento que o banco real não tem: `table.get()` devolve sempre o
MESMO objeto, então uma mutação feita pelo código fica visível na leitura
seguinte mesmo sem `update()`. Foi exatamente esse apelidamento que
escondeu o defeito corrigido em `_remove_from_local_db` (FIX-PM-06).

Aqui nada é mockado além do HTTP: cada teste escreve e lê um arquivo de
verdade em `tmp_path`.
"""

import json
import os

import pytest

from param_manager.manager import ParamManager

SENHA_EM_CLARO = 'SenhaSuperSecreta123'


@pytest.fixture
def pm_disco(requests_mock, monkeypatch, tmp_path):
    """ParamManager com TinyDB real, isolado em tmp_path."""
    ParamManager._instances = {}
    monkeypatch.setenv('PARAMS_USERNAME', 'test_user')
    monkeypatch.setenv('PARAMS_PASSWORD', 'secret_pass')
    monkeypatch.setenv('API_PARAMS_URL', '')
    monkeypatch.setenv('CHAVE_CUSTODIA_APP', '123456')

    pm = ParamManager(
        api_url='http://test-api.example.com',
        instance_name='integracao',
        cache_duration=60,
        timeout=2,
        local_db_path=str(tmp_path),
    )
    pm._token = None
    pm._refresh_token = None
    pm._token_expire_at = 0

    yield pm, requests_mock

    pm._db.close()
    ParamManager._instances = {}


def _ler_arquivo(pm):
    """Conteúdo bruto do arquivo TinyDB, como está em disco."""
    with open(pm._db_path, encoding='utf-8') as fh:
        return fh.read()


@pytest.mark.integracao
def test_arquivo_e_criado_em_disco(pm_disco):
    """O caminho anunciado pelo gerenciador existe de fato."""
    pm, _ = pm_disco
    pm._save_to_local_db('finance', {'limite': {'type': 'int', 'value': 10}})

    assert os.path.isfile(pm._db_path)
    assert 'params_integracao.json' in pm._db_path


@pytest.mark.integracao
def test_dados_sobrevivem_a_uma_nova_instancia(pm_disco, tmp_path):
    """
    O que foi gravado é lido de volta por outro objeto.

    Prova que a persistência é do arquivo, não do cache em memória: o
    multiton é zerado e um gerenciador novo é construído sobre o mesmo
    diretório.
    """
    pm, _ = pm_disco
    pm._save_to_local_db('finance', {'limite': {'type': 'int', 'value': 10}})
    pm._db.close()

    ParamManager._instances = {}
    outro = ParamManager(
        api_url='http://test-api.example.com',
        instance_name='integracao',
        cache_duration=60,
        timeout=2,
        local_db_path=str(tmp_path),
    )

    recuperado = outro._get_from_local_db('finance')
    assert recuperado['limite']['value'] == 10
    outro._db.close()


@pytest.mark.integracao
def test_remocao_de_valor_nulo_persiste_no_arquivo(pm_disco):
    """
    FIX-PM-06 contra o banco real.

    O equivalente unitário passa mesmo com o defeito presente, porque o
    `MagicMock` devolve o mesmo dict em toda leitura. Aqui a remoção só
    sobrevive se `update()` tiver sido chamado de verdade.
    """
    pm, _ = pm_disco
    pm._save_to_local_db(
        'finance',
        {'limite': None, 'outro': {'type': 'int', 'value': 42}},
    )

    pm._remove_from_local_db('finance', 'limite')

    registro = pm._get_from_local_db('finance')
    assert 'limite' not in registro
    assert registro['outro']['value'] == 42

    # E o arquivo em disco também não pode mais citar a chave.
    assert '"limite"' not in _ler_arquivo(pm)


@pytest.mark.integracao
def test_remocao_de_chave_ausente_nao_corrompe_o_registro(pm_disco):
    """Remover algo que não existe deixa o restante intacto."""
    pm, _ = pm_disco
    pm._save_to_local_db('finance', {'outro': {'type': 'int', 'value': 42}})

    pm._remove_from_local_db('finance', 'inexistente')

    registro = pm._get_from_local_db('finance')
    assert registro['outro']['value'] == 42


@pytest.mark.integracao
def test_secret_em_claro_nunca_chega_ao_arquivo(pm_disco):
    """
    A guarda de última linha vale contra o disco, não só contra o mock.

    Um parâmetro sensível sem envelope é descartado; os demais continuam
    sendo gravados.
    """
    pm, _ = pm_disco
    pm._save_to_local_db(
        'cofre',
        {
            'senha': {'type': 'secret', 'value': SENHA_EM_CLARO},
            'limite': {'type': 'int', 'value': 10},
        },
    )

    bruto = _ler_arquivo(pm)
    assert SENHA_EM_CLARO not in bruto

    registro = pm._get_from_local_db('cofre')
    assert 'senha' not in registro
    assert registro['limite']['value'] == 10


@pytest.mark.integracao
def test_fallback_offline_le_do_arquivo(pm_disco):
    """
    Com a API fora, a leitura vem do arquivo gravado antes.

    É o cenário que justifica a persistência local existir.
    """
    pm, requests_mock = pm_disco
    pm._save_to_local_db('finance', {'limite': {'type': 'int', 'value': 77}})

    requests_mock.post(
        'http://test-api.example.com/auth/token',
        json={'access_token': 'T', 'refresh_token': 'R'},
        status_code=200,
    )
    requests_mock.get(
        'http://test-api.example.com/parameters/apps/finance/params/',
        status_code=500,
    )

    devolvido = pm.get_all_params('finance')
    assert devolvido['limite']['value'] == 77


@pytest.mark.integracao
def test_erro_de_leitura_descarta_apenas_a_tabela_do_app(pm_disco):
    """
    PM-03 contra o banco real: um app quebrado não derruba os outros.

    O `drop_table` precisa atingir só a tabela do app envolvido — com o
    banco real, apagar demais é irreversível.
    """
    pm, requests_mock = pm_disco
    pm._save_to_local_db('finance', {'limite': {'type': 'int', 'value': 1}})
    pm._save_to_local_db('vendas', {'meta': {'type': 'int', 'value': 2}})

    requests_mock.post(
        'http://test-api.example.com/auth/token',
        json={'access_token': 'T', 'refresh_token': 'R'},
        status_code=200,
    )
    requests_mock.get(
        'http://test-api.example.com/parameters/apps/finance/params/',
        text='isso nao e json',
        status_code=200,
    )

    assert pm.get_all_params('finance') == {}

    # A tabela do outro app continua legível no arquivo.
    assert pm._get_from_local_db('vendas')['meta']['value'] == 2


@pytest.mark.integracao
def test_arquivo_permanece_json_valido_apos_o_ciclo(pm_disco):
    """Depois de gravar, remover e regravar, o arquivo ainda abre."""
    pm, _ = pm_disco
    pm._save_to_local_db('finance', {'a': {'type': 'int', 'value': 1}})
    pm._remove_from_local_db('finance', 'a')
    pm._save_to_local_db('finance', {'b': {'type': 'int', 'value': 2}})

    conteudo = json.loads(_ler_arquivo(pm))
    assert isinstance(conteudo, dict)
    assert pm._get_from_local_db('finance')['b']['value'] == 2
