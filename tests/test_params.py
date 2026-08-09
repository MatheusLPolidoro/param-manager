import copy
import json
import threading
import time
from unittest.mock import patch

import pytest
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

from param_manager.manager import ParamManager

SENHA_EM_CLARO = "SenhaSuperSecreta123"


def _cifrar(dado: bytes, chave: bytes) -> dict:
    """Reproduz o encrypt() do servidor: AES-GCM, IV de 12 bytes, hex."""
    iv = get_random_bytes(12)
    cipher = AES.new(chave, AES.MODE_GCM, iv)
    dados_cifrados, tag = cipher.encrypt_and_digest(dado)
    return {
        "iv": iv.hex(),
        "tag": tag.hex(),
        "data": dados_cifrados.hex(),
    }


def _montar_envelope(segredo: str, chave_custodia_app: str = "123456") -> dict:
    """
    Monta o envelope de duas camadas exatamente como o servidor grava.

    Contrato congelado: PBKDF2(count=100_000, dkLen=32, SHA256) + AES-GCM.
    """
    salt = get_random_bytes(16)
    chave_custodia = PBKDF2(
        chave_custodia_app.encode(),
        salt,
        dkLen=32,
        count=100_000,
        hmac_hash_module=SHA256,
    )
    master_key = get_random_bytes(32)
    return {
        "salt": salt.hex(),
        "master_key": _cifrar(master_key, chave_custodia),
        "crypto_data": _cifrar(segredo.encode(), master_key),
    }


def test_save_to_local_db_nunca_grava_secret_em_claro(setup_param_manager):
    """PM-01: o texto claro não pode escapar para o cache nem para o disco."""
    pm, mock_table, requests_mock = setup_param_manager

    envelope = _montar_envelope(SENHA_EM_CLARO)
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/cofre/params/",
        json={"params": {"senha": {"type": "secret", "value": envelope}}},
        status_code=200,
    )

    devolvido = pm.get_all_params("cofre")

    # O chamador continua recebendo o valor decifrado.
    assert devolvido["senha"]["value"] == SENHA_EM_CLARO

    # O cache em memória guarda apenas o envelope.
    assert pm._cache["cofre"]["senha"]["value"] == envelope

    # E nada do que foi persistido contém o texto claro.
    persistido = json.dumps(
        [
            {"args": str(c.args), "kwargs": str(c.kwargs)}
            for c in mock_table.insert.call_args_list
            + mock_table.update.call_args_list
        ]
    )
    assert SENHA_EM_CLARO not in persistido
    assert envelope["crypto_data"]["data"] in persistido


def test_save_to_local_db_descarta_secret_nao_cifrado(setup_param_manager):
    """PM-01: guarda de última linha contra valor sensível em claro."""
    pm, mock_table, requests_mock = setup_param_manager

    pm._save_to_local_db(
        "cofre",
        {
            "senha": {"type": "secret", "value": SENHA_EM_CLARO},
            "limite": {"type": "int", "value": 10},
        },
    )

    # Com TinyDB mockado, table.get() é truthy e o código usa update().
    chamada = mock_table.update.call_args or mock_table.insert.call_args
    gravado = chamada[0][0]["params"]
    assert "senha" not in gravado
    assert gravado["limite"]["value"] == 10


def test_invalidacao_de_cache_remove_apenas_a_tabela_do_app(
    setup_param_manager,
):
    """PM-03: drop_table(app), nunca drop_tables()."""
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        text="isso nao e json",
        status_code=200,
    )

    assert pm.get_all_params("finance") == {}
    pm._db.drop_table.assert_called_once_with("finance")
    pm._db.drop_tables.assert_not_called()
    pm._db.purge_tables.assert_not_called()


def test_get_envia_authorization_quando_ha_credencial(setup_param_manager):
    """PM-11: leitura passa a mandar o header quando há credencial."""
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "TOK123", "refresh_token": "RR"},
        status_code=200,
    )
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        json={"params": {"limite": {"type": "int", "value": 7}}},
        status_code=200,
    )

    assert pm.get_all_params("finance")["limite"]["value"] == 7
    assert (
        requests_mock.last_request.headers["Authorization"] == "Bearer TOK123"
    )


def test_get_sem_credencial_continua_funcionando(setup_param_manager):
    """PM-11: sem credencial, a leitura anônima não pode quebrar."""
    pm, mock_table, requests_mock = setup_param_manager
    pm._username = None
    pm._password = None

    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        json={"params": {"limite": {"type": "int", "value": 7}}},
        status_code=200,
    )

    assert pm.get_all_params("finance")["limite"]["value"] == 7
    assert "Authorization" not in requests_mock.last_request.headers


def test_auth_post_usa_timeout(setup_param_manager):
    """PM-05: o POST de autenticação não pode ficar sem timeout."""
    pm, mock_table, requests_mock = setup_param_manager

    with patch("param_manager.manager.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "T",
            "refresh_token": "R",
        }
        pm._auth_get_token()

    assert mock_post.call_args.kwargs["timeout"] == pm._timeout


def test_token_renovado_uma_vez_sob_concorrencia(setup_param_manager):
    """PM-05: N threads concorrentes disparam uma única renovação."""
    pm, mock_table, requests_mock = setup_param_manager
    chamadas = []

    def _fake_token():
        chamadas.append(1)
        time.sleep(0.05)
        pm._token = "TOK"
        pm._token_expire_at = time.time() + 600
        return pm._token

    with patch.object(pm, "_auth_get_token", side_effect=_fake_token):
        threads = [
            threading.Thread(target=pm._get_valid_token) for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(chamadas) == 1


def test_verify_ssl_default_permanece_false(tmp_path):
    """PM-06: default False, pois o ambiente usa certificado interno."""
    ParamManager._instances = {}
    pm = ParamManager(
        api_url="http://x.example.com",
        instance_name="d1",
        local_db_path=str(tmp_path),
    )
    assert pm._verify_ssl is False


def test_verify_ssl_precedencia_construtor_sobre_env(monkeypatch, tmp_path):
    """PM-06: construtor > {INSTANCE}_VERIFY_SSL > VERIFY_SSL."""
    ParamManager._instances = {}
    monkeypatch.setenv("VERIFY_SSL", "false")
    monkeypatch.setenv("D2_VERIFY_SSL", "false")

    pm = ParamManager(
        api_url="http://x.example.com",
        instance_name="d2",
        verify_ssl=True,
        local_db_path=str(tmp_path),
    )
    assert pm._verify_ssl is True

    ParamManager._instances = {}
    monkeypatch.setenv("D3_VERIFY_SSL", "true")
    pm3 = ParamManager(
        api_url="http://x.example.com",
        instance_name="d3",
        local_db_path=str(tmp_path),
    )
    assert pm3._verify_ssl is True


def test_excecao_generica_arma_circuit_breaker(setup_param_manager):
    """PM-08: erro HTTP também precisa ativar o cooldown."""
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        json={"detail": "boom"},
        status_code=500,
    )

    pm.get_all_params("finance")
    assert "finance" in pm._api_error_timestamp
    assert pm._breaker_ativo("finance")


def test_import_star_funciona():
    """PM-09: __all__ não pode listar símbolo inexistente."""
    import param_manager

    for nome in param_manager.__all__:
        assert hasattr(param_manager, nome), nome


def test_upsert_params(setup_param_manager):
    pm, mock_table, requests_mock = setup_param_manager

    # Mock do token
    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "TOK", "refresh_token": "RR"},
        status_code=200,
    )

    # Mock do PUT esperado
    requests_mock.put(
        "http://test-api.example.com/parameters/apps/finance/params/",
        json={
            "params": {
                "limit": {"type": "int", "value": 99}
            }
        },
        status_code=200,
    )

    # Chamada correta usando a NOVA assinatura:
    res = pm.upsert_params(
        "finance",
        "limit",
        value=99,
        param_type="int",
    )

    assert res["params"]["limit"]["value"] == 99
    assert res["params"]["limit"]["type"] == "int"


def test_delete_param(setup_param_manager):
    pm, mock_table, requests_mock = setup_param_manager

    # simula cache inicial
    pm._cache["finance"] = {"limit": {"value": 1}}
    pm._cache_timestamp["finance"] = 123

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "TT", "refresh_token": "RR"},
        status_code=200,
    )

    requests_mock.delete(
        "http://test-api.example.com/parameters/apps/finance/params/limit",
        json={"status": "deleted"},
        status_code=200,
    )

    res = pm.delete_param("finance", "limit")

    assert res["status"] == "deleted"
    assert "limit" not in pm._cache["finance"]


def test_erro_de_leitura_local_descarta_so_a_tabela_do_app(
    setup_param_manager,
):
    """
    FIX-PM-01: um registro ilegível de um app não pode apagar o cache
    offline de todos os outros — e este caminho roda justamente durante
    indisponibilidade da API.
    """
    pm, mock_table, requests_mock = setup_param_manager
    mock_table.all.side_effect = RuntimeError("registro corrompido")

    assert pm._get_from_local_db("finance") == {}

    pm._db.drop_table.assert_called_once_with("finance")
    pm._db.drop_tables.assert_not_called()


def test_retry_de_401_renova_token_uma_unica_vez(setup_param_manager):
    """
    FIX-PM-02: N threads em 401 simultâneo disparam UMA renovação.

    Sem o lock, cada uma faria POST /auth/refresh com o mesmo refresh
    token de uso único e uma invalidaria a sessão da outra.
    """
    pm, mock_table, requests_mock = setup_param_manager
    pm._token = "TOKEN_VELHO"
    pm._token_expire_at = time.time() + 600
    renovacoes = []

    def _fake_refresh():
        renovacoes.append(1)
        time.sleep(0.05)
        pm._token = "TOKEN_NOVO"
        pm._token_expire_at = time.time() + 600
        return pm._token

    with patch.object(pm, "_auth_refresh_token", side_effect=_fake_refresh):
        threads = [
            threading.Thread(target=pm._force_token_refresh)
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(renovacoes) == 1
    assert pm._token == "TOKEN_NOVO"


def _param_users(qtd=2):
    return {
        "type": "users",
        "value": [
            {
                "user_id": str(i),
                "user": f"u{i}",
                "password": _montar_envelope(f"{SENHA_EM_CLARO}{i}"),
                "status": True,
            }
            for i in range(qtd)
        ],
    }


def test_users_decifra_sem_mutar_o_cache(setup_param_manager):
    """TEST-04: a garantia de não-mutação vale também para `users`."""
    pm, mock_table, requests_mock = setup_param_manager
    param = _param_users()
    envelope_original = copy.deepcopy(param["value"][0]["password"])

    requests_mock.get(
        "http://test-api.example.com/parameters/apps/cofre/params/",
        json={"params": {"equipe": param}},
        status_code=200,
    )

    devolvido = pm.get_all_params("cofre")
    assert devolvido["equipe"]["value"][0]["password"] == (
        f"{SENHA_EM_CLARO}0"
    )
    assert pm._cache["cofre"]["equipe"]["value"][0]["password"] == (
        envelope_original
    )


def test_user_decifra_sem_mutar_o_cache(setup_param_manager):
    """TEST-04: idem para o tipo `user`."""
    pm, mock_table, requests_mock = setup_param_manager
    envelope = _montar_envelope(SENHA_EM_CLARO)
    param = {
        "type": "user",
        "value": {
            "user_id": "1",
            "user": "joao",
            "password": envelope,
            "status": True,
        },
    }

    requests_mock.get(
        "http://test-api.example.com/parameters/apps/cofre/params/",
        json={"params": {"admin": param}},
        status_code=200,
    )

    devolvido = pm.get_all_params("cofre")
    assert devolvido["admin"]["value"]["password"] == SENHA_EM_CLARO
    assert pm._cache["cofre"]["admin"]["value"]["password"] == envelope


def test_cooldown_usa_variavel_propria(monkeypatch, tmp_path):
    """FIX-PM-05: sem config, cai em _cache_duration (comportamento antigo)."""
    ParamManager._instances = {}
    pm = ParamManager(
        api_url="http://x.example.com",
        instance_name="cd1",
        cache_duration=3600,
        local_db_path=str(tmp_path),
    )
    assert pm._api_error_cooldown is None
    assert pm._effective_cooldown == pm._cache_duration

    ParamManager._instances = {}
    monkeypatch.setenv("CD2_API_ERROR_COOLDOWN", "30")
    pm2 = ParamManager(
        api_url="http://x.example.com",
        instance_name="cd2",
        cache_duration=3600,
        local_db_path=str(tmp_path),
    )
    assert pm2._effective_cooldown == 30
    assert pm2._cache_duration == 3600


def test_instance_name_posicional_registra_no_slot_correto(tmp_path):
    """FIX-PM-03: chamada posicional não pode cair no slot 'default'."""
    ParamManager._instances = {}
    pm = ParamManager(
        "http://x.example.com", 300, 5, str(tmp_path), "u", "p", "billing"
    )

    assert "billing" in ParamManager._instances
    assert ParamManager._instances["billing"] is pm
    assert pm._instance_name == "billing"

    # E a instância default continua sendo outra coisa.
    outra = ParamManager(instance_name="default", local_db_path=str(tmp_path))
    assert outra is not pm


def test_delete_param_remove_do_banco_local(setup_param_manager):
    """FIX-PM-04: parâmetro apagado não pode sobreviver no fallback."""
    pm, mock_table, requests_mock = setup_param_manager
    mock_table.get.return_value = {
        "timestamp": 1,
        "params": {"limite": {"type": "int", "value": 1}},
    }

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.delete(
        "http://test-api.example.com/parameters/apps/finance/params/limite",
        json={"status": "deleted"},
        status_code=200,
    )

    pm.delete_param("finance", "limite")

    gravado = mock_table.update.call_args_list[0][0][0]["params"]
    assert "limite" not in gravado


def test_remove_from_local_db_com_valor_none(setup_param_manager):
    """
    FIX-PM-06: parâmetro com valor None deve ser removido do banco local.

    A guarda anterior fazia pop() e depois retornava se fosse None,
    deixando a chave no registro persistido.
    """
    pm, mock_table, requests_mock = setup_param_manager
    REGISTRO = {
        'timestamp': time.time(),
        'params': {'limite': None, 'outro': {'type': 'int', 'value': 42}},
    }
    # Simula leitura fresca em cada chamada, evitando aliasing do mock
    mock_table.get.side_effect = lambda *a, **k: copy.deepcopy(REGISTRO)

    pm._remove_from_local_db('finance', 'limite')

    # Verifica que update foi chamado
    mock_table.update.assert_called_once()
    # Verifica que 'limite' foi removido mas 'outro' permanece
    gravado = mock_table.update.call_args_list[0][0][0]['params']
    assert 'limite' not in gravado
    assert 'outro' in gravado
    assert gravado['outro'] == {'type': 'int', 'value': 42}


def test_remove_from_local_db_chave_ausente(setup_param_manager):
    """
    Quando a chave não existe, update não é chamado.
    """
    pm, mock_table, requests_mock = setup_param_manager
    REGISTRO = {
        'timestamp': time.time(),
        'params': {'outro': {'type': 'int', 'value': 42}},
    }
    mock_table.get.side_effect = lambda *a, **k: copy.deepcopy(REGISTRO)

    pm._remove_from_local_db('finance', 'inexistente')

    # update não deve ser chamado quando a chave não existe
    mock_table.update.assert_not_called()


def test_remove_from_local_db_excecao_engolida(setup_param_manager):
    """
    Exceção durante leitura/escrita não escapa (mesmo padrão do FIX-PM-01).
    """
    pm, mock_table, requests_mock = setup_param_manager
    mock_table.get.side_effect = RuntimeError('registro corrompido')

    # Não deve lançar exceção
    pm._remove_from_local_db('finance', 'qualquer')

    # A exceção é apenas logada, não propagada
    # (verificável via captura de logs se necessário, mas a ausência de
    # exceção aqui confirma o comportamento)


def test_delete_param_invalida_cache_por_parametro(setup_param_manager):
    """
    FIX-PM-07: delete_param invalida _param_cache por parâmetro.

    Antes, get_param seguinte batia em _is_param_cache_valid e devolvia
    o valor apagado — possivelmente uma credencial revogada — por até
    _cache_duration (3600s com get_instance).
    """
    pm, mock_table, requests_mock = setup_param_manager

    # Semeia cache por parâmetro
    pm._cache['finance'] = {
        'limite': {'type': 'int', 'value': 100},
        'outro': {'type': 'int', 'value': 200},
    }
    pm._cache_timestamp['finance'] = time.time()

    pm._param_cache['finance:limite'] = {'type': 'int', 'value': 100}
    pm._param_cache_timestamp['finance:limite'] = time.time()
    pm._param_cache['finance:outro'] = {'type': 'int', 'value': 200}
    pm._param_cache_timestamp['finance:outro'] = time.time()

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.delete(
        "http://test-api.example.com/parameters/apps/finance/params/limite",
        json={"status": "deleted"},
        status_code=200,
    )

    pm.delete_param("finance", "limite")

    # Verifica que limite foi removido do cache por parâmetro
    assert 'finance:limite' not in pm._param_cache
    assert 'finance:limite' not in pm._param_cache_timestamp

    # Verifica que outro permanece intacto (não usou ramo por-app)
    assert 'finance:outro' in pm._param_cache
    assert 'finance:outro' in pm._param_cache_timestamp


def test_delete_param_nao_chama_save_redundante(setup_param_manager):
    """
    FIX-PM-07b: remover escrita redundante de _save_to_local_db.

    Antes, delete_param chamava _save_to_local_db(app_name, params)
    logo após _remove_from_local_db. Era segunda aquisição de self._lock
    sem efeito — a chave já saiu de self._cache antes.
    """
    pm, mock_table, requests_mock = setup_param_manager

    pm._cache['finance'] = {'limite': {'type': 'int', 'value': 100}}
    pm._cache_timestamp['finance'] = time.time()

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.delete(
        "http://test-api.example.com/parameters/apps/finance/params/limite",
        json={"status": "deleted"},
        status_code=200,
    )

    with patch.object(pm, '_save_to_local_db') as save:
        pm.delete_param("finance", "limite")
        # Não deve chamar _save_to_local_db
        save.assert_not_called()


def test_delete_param_404_cai_em_get_param(setup_param_manager):
    """
    FIX-PM-07c: ponta a ponta — GET 404 após delete (COMPORTAMENTO CORRIGIDO).

    Sem cache por-param, get_param desce até _fetch_param_from_api,
    toma 404, e agora é tratado como ParamNaoEncontradoError que NÃO arma
    o circuit breaker — 404 significa "recurso ausente", não "servidor
    indisponível". A biblioteca retorna None (fallback offline vazio),
    permitindo consultas futuras sem entrar em cooldown.

    Este teste registra que o comportamento foi corrigido em relação ao
    registro anterior.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/limite",
        status_code=404,
    )

    resultado = pm.get_param("finance", "limite")

    # Sem cache por-param, cai em fallback offline (que é vazio)
    assert resultado is None

    # Circuit breaker NÃO é ativado para 404 — só para indisponibilidade real
    assert 'finance' not in pm._api_error_timestamp


def test_upsert_params_invalida_cache_por_parametro(setup_param_manager):
    """
    FIX-PM-08: upsert_params invalida _param_cache por parâmetro.

    Antes, get_param seguinte batia em _is_param_cache_valid e devolvia
    o valor anterior — por até _cache_duration (3600s com get_instance).
    Agora, clear_cache por parâmetro invalida a entrada específica.

    Além disso, o get_param seguinte não faz rede: cai no ramo do cache
    do app (que acabou de ser atualizado com timestamp fresco) e repopula
    a entrada por parâmetro sozinho.
    """
    pm, mock_table, requests_mock = setup_param_manager

    # Semeia cache por parâmetro
    pm._cache['finance'] = {
        'limit': {'type': 'int', 'value': 100},
        'outro': {'type': 'int', 'value': 200},
    }
    pm._cache_timestamp['finance'] = time.time()

    pm._param_cache['finance:limit'] = {'type': 'int', 'value': 100}
    pm._param_cache_timestamp['finance:limit'] = time.time()
    pm._param_cache['finance:outro'] = {'type': 'int', 'value': 200}
    pm._param_cache_timestamp['finance:outro'] = time.time()

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.put(
        "http://test-api.example.com/parameters/apps/finance/params/",
        json={"params": {"limit": {"type": "int", "value": 99}}},
        status_code=200,
    )

    pm.upsert_params("finance", "limit", value=99, param_type="int")

    # Verifica que limit foi removido do cache por parâmetro
    assert 'finance:limit' not in pm._param_cache
    assert 'finance:limit' not in pm._param_cache_timestamp

    # Verifica que outro permanece intacto (não usou ramo por-app)
    assert 'finance:outro' in pm._param_cache
    assert 'finance:outro' in pm._param_cache_timestamp

    # get_param seguinte retorna o novo valor sem fazer GET
    resultado = pm.get_param("finance", "limit")
    assert resultado == 99

    # Verifica que nenhuma requisição GET foi feita
    # (apenas POST de token e PUT de upsert)
    for req in requests_mock.request_history:
        assert req.method != "GET"


@pytest.mark.parametrize(
    'valor_invalido',
    ['', ' ', '300s', 'abc', '30.5', '-5'],
)
def test_api_error_cooldown_invalido_usa_cache_duration(
    valor_invalido, monkeypatch, tmp_path, caplog
):
    """
    FIX-PM-09: valores inválidos de API_ERROR_COOLDOWN não levantam,
    caem no fallback de cache_duration com warning.
    """
    ParamManager._instances = {}
    instance_name = f'test_invalid_{id(valor_invalido)}'
    monkeypatch.setenv(f'{instance_name.upper()}_API_ERROR_COOLDOWN', valor_invalido)

    pm = ParamManager(
        api_url='http://x.example.com',
        instance_name=instance_name,
        cache_duration=600,
        local_db_path=str(tmp_path),
    )

    # Instância está completamente inicializada
    assert pm._initialized is True
    assert pm._db is not None

    # Valor inválido caiu no fallback
    assert pm._api_error_cooldown is None
    assert pm._effective_cooldown == pm._cache_duration

    # Houve aviso
    assert any('API_ERROR_COOLDOWN' in record.message for record in caplog.records if record.levelname == 'WARNING')


@pytest.mark.parametrize('valor_valido,esperado', [
    ('30', 30),
    (' 30 ', 30),
    ('0', 0),
])
def test_api_error_cooldown_valido_parseado(
    valor_valido, esperado, monkeypatch, tmp_path
):
    """
    FIX-PM-09: valores válidos de API_ERROR_COOLDOWN são parseados
    corretamente sem levantamento.
    """
    ParamManager._instances = {}
    instance_name = f'test_valid_{id(valor_valido)}'
    monkeypatch.setenv(f'{instance_name.upper()}_API_ERROR_COOLDOWN', valor_valido)

    pm = ParamManager(
        api_url='http://x.example.com',
        instance_name=instance_name,
        cache_duration=600,
        local_db_path=str(tmp_path),
    )

    # Instância está completamente inicializada
    assert pm._initialized is True
    assert pm._db is not None

    # Valor válido foi parseado
    assert pm._api_error_cooldown == esperado
    assert pm._effective_cooldown == esperado


def test_api_error_cooldown_zero_desativa_circuit_breaker(
    monkeypatch, tmp_path
):
    """
    FIX-PM-09: valor 0 é válido e desativa o circuit breaker
    (verifica que _is_api_error_cached devolve False).
    """
    ParamManager._instances = {}
    monkeypatch.setenv('TEST_ZERO_API_ERROR_COOLDOWN', '0')

    pm = ParamManager(
        api_url='http://x.example.com',
        instance_name='test_zero',
        cache_duration=600,
        local_db_path=str(tmp_path),
    )

    # Valor 0 foi parseado e desativa o circuit breaker
    assert pm._api_error_cooldown == 0
    assert pm._effective_cooldown == 0

    # Simular timestamp de erro (time.time() retorna sempre False porque
    # 0 segundos passaram, logo current_time - error_time é sempre >= 0)
    pm._api_error_timestamp['test_app'] = time.time()
    assert pm._breaker_ativo('test_app') is False


@pytest.mark.parametrize('valor', ['', '  ', 'abc', '30s', '10.5'])
def test_cache_duration_invalido_cai_no_fallback(valor, monkeypatch, tmp_path, caplog):
    """
    FIX-PM-10: CACHE_DURATION malformado não pode derrubar a construção.

    Mesmo motivo do API_ERROR_COOLDOWN: o ValueError subia depois de
    __new__ ter registrado a instância, deixando um objeto meio-construído
    e permanentemente inutilizável no multiton.
    """
    ParamManager._instances = {}
    monkeypatch.setenv('CACHE_DURATION', valor)

    with caplog.at_level('WARNING'):
        pm = ParamManager(
            api_url='http://x.example.com',
            instance_name='cd_ruim',
            cache_duration=60,
            local_db_path=str(tmp_path),
        )

    assert pm._cache_duration == 60
    assert pm._initialized is True
    assert pm._db is not None
    assert any('CACHE_DURATION' in r.message for r in caplog.records)


def test_cache_duration_negativo_vira_zero_e_nunca_cacheia(monkeypatch, tmp_path):
    """
    FIX-PM-10: negativo mantém "nunca cacheia", não vira cache de 1h.

    Hoje um valor negativo faz _is_cache_valid devolver sempre False.
    Mandá-lo ao fallback trocaria isso por cache longo — afrouxamento
    silencioso numa lib que serve `secret`. O assert de comportamento,
    e não só do campo, é o que protege a invariante.
    """
    ParamManager._instances = {}
    monkeypatch.setenv('CACHE_DURATION', '-1')

    pm = ParamManager(
        api_url='http://x.example.com',
        instance_name='cd_negativo',
        cache_duration=3600,
        local_db_path=str(tmp_path),
    )

    assert pm._cache_duration == 0

    pm._cache['finance'] = {'limite': {'type': 'int', 'value': 1}}
    pm._cache_timestamp['finance'] = time.time()
    assert pm._is_cache_valid('finance') is False


@pytest.mark.parametrize('valor', ['', 'abc', '5s'])
def test_timeout_invalido_cai_no_fallback(valor, monkeypatch, tmp_path):
    """FIX-PM-10: TIMEOUT malformado também não derruba a construção."""
    ParamManager._instances = {}
    monkeypatch.setenv('TIMEOUT', valor)

    pm = ParamManager(
        api_url='http://x.example.com',
        instance_name='to_ruim',
        timeout=7,
        local_db_path=str(tmp_path),
    )

    assert pm._timeout == 7
    assert pm._initialized is True
    assert pm._db is not None


def test_instancia_segue_utilizavel_apos_valor_invalido(monkeypatch, tmp_path):
    """
    FIX-PM-10: regressão do motivo original.

    Antes, a exceção no __init__ deixava no multiton um objeto sem _db e
    sem caches; a chamada seguinte devolvia esse cadáver e o consumidor
    tomava AttributeError sem relação com o erro real.
    """
    ParamManager._instances = {}
    monkeypatch.setenv('CACHE_DURATION', 'nao-e-numero')

    ParamManager(
        api_url='http://x.example.com',
        instance_name='sobrevivente',
        cache_duration=42,
        local_db_path=str(tmp_path),
    )
    segunda = ParamManager(
        api_url='http://x.example.com',
        instance_name='sobrevivente',
        local_db_path=str(tmp_path),
    )

    assert segunda._db is not None
    assert segunda._cache_duration == 42
    assert segunda.get_cache_info() is not None


def test_404_get_param_nao_arma_breaker(setup_param_manager):
    """
    FIX-PM-11: 404 em get_param NÃO arma circuit breaker.

    Um 404 significa "recurso não encontrado", não "servidor indisponível".
    Portanto, _api_error_timestamp deve permanecer vazio.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/saldo",
        status_code=404,
    )

    resultado = pm.get_param("finance", "saldo")
    assert resultado is None
    assert 'finance' not in pm._api_error_timestamp


def test_404_get_param_depois_200_bate_api(setup_param_manager):
    """
    FIX-PM-11: 404 seguido de 200 em get_param bate na API.

    Como 404 não arma o breaker, a próxima chamada deve fazer uma nova
    requisição à API em vez de usar fallback offline.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    # Primeira chamada retorna 404
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/saldo",
        [
            {"status_code": 404},
            {
                "json": {"param": {"type": "int", "value": 1000}},
                "status_code": 200,
            },
        ],
    )

    # Primeira chamada: 404
    resultado1 = pm.get_param("finance", "saldo")
    assert resultado1 is None

    # Segunda chamada: bate na API e retorna 200
    resultado2 = pm.get_param("finance", "saldo")
    assert resultado2 == 1000


def test_500_em_get_param_continua_armando_breaker(setup_param_manager):
    """
    FIX-PM-11: 500 em get_param CONTINUA armando o circuit breaker.

    Um 500 (erro de servidor) deve ativar o cooldown normalmente.
    Regressão: este teste garante que apenas 404 é tratado diferentemente.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/saldo",
        status_code=500,
    )

    resultado = pm.get_param("finance", "saldo")
    assert resultado is None
    assert 'finance' in pm._api_error_timestamp


def test_401_em_get_param_continua_armando_breaker(setup_param_manager):
    """
    FIX-PM-11: 401 em get_param CONTINUA armando o circuit breaker.

    Um 401 (não autorizado) deve ativar o cooldown normalmente.
    Regressão: este teste garante que apenas 404 é tratado diferentemente.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/saldo",
        status_code=401,
    )

    resultado = pm.get_param("finance", "saldo")
    assert resultado is None
    assert 'finance' in pm._api_error_timestamp


def test_404_get_all_params_nao_arma_breaker(setup_param_manager):
    """
    FIX-PM-11: 404 em get_all_params NÃO arma circuit breaker.

    Um 404 em get_all_params deve ter o mesmo comportamento que em
    get_param: não ativa o cooldown.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        status_code=404,
    )

    resultado = pm.get_all_params("finance")
    assert resultado == {}
    assert 'finance' not in pm._api_error_timestamp


def test_404_nao_desarma_breaker_ja_armado(setup_param_manager):
    """
    FIX-PM-11: 404 NÃO desarma um breaker já armado.

    Se o breaker está armado por um erro real (500, timeout),
    um 404 subsequente não deve limpá-lo. O breaker só é desarmado
    por uma resposta 200.
    """
    pm, mock_table, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "T", "refresh_token": "R"},
        status_code=200,
    )

    # Primeiro, arma o breaker com um 500
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        status_code=500,
    )
    pm.get_all_params("finance")
    assert 'finance' in pm._api_error_timestamp

    # Reset o mock para retornar 404 na próxima chamada
    requests_mock.get(
        "http://test-api.example.com/parameters/apps/finance/params/",
        status_code=404,
    )

    # Chama novamente: o breaker já está armado, vai usar fallback
    pm.get_all_params("finance")

    # O breaker deve CONTINUAR armado (404 não o limpa)
    assert 'finance' in pm._api_error_timestamp


# --- CL-2: travamento de cache e breaker -------------------------------


def test_get_cache_info_sobrevive_mutacao_durante_iteracao(
    setup_param_manager,
):
    """
    R1: get_cache_info percorre snapshots, não os dicts vivos.

    Concorrência simulada de dentro da iteração: _is_cache_valid muta
    _cache_timestamp na primeira chave, como faria um clear_cache de
    outra thread. Sem o snapshot isso é RuntimeError: dictionary
    changed size during iteration.
    """
    pm, *_ = setup_param_manager

    agora = time.time()
    for app in ('app_a', 'app_b', 'app_c'):
        pm._cache[app] = {'P': {'type': 'int', 'value': 1}}
        pm._cache_timestamp[app] = agora
    pm._api_error_timestamp['app_a'] = agora

    original = pm._is_cache_valid
    ja_mutou = []

    def muta_na_primeira_chave(app_name):
        if not ja_mutou:
            ja_mutou.append(app_name)
            pm._cache_timestamp.pop('app_c', None)
            pm._api_error_timestamp['app_z'] = agora
        return original(app_name)

    pm._is_cache_valid = muta_na_primeira_chave

    info = pm.get_cache_info()

    assert ja_mutou, 'a mutação concorrente não chegou a ser exercitada'
    assert 'app_a' in info['cache_timestamps']


def test_process_parameters_sobrevive_mutacao_do_cache(setup_param_manager):
    """
    R1: get_all_params decifra sobre um snapshot, não sobre o cache vivo.

    O side_effect grava uma chave nova em _cache[app] no meio da
    comprehension de _process_parameters. Sem o snapshot, estoura.
    """
    pm, *_ = setup_param_manager

    pm._cache['finance'] = {
        'A': {'type': 'int', 'value': 1},
        'B': {'type': 'int', 'value': 2},
    }
    pm._cache_timestamp['finance'] = time.time()

    original = ParamManager._process_parameter
    ja_mutou = []

    def muta_na_primeira_chave(param):
        if not ja_mutou:
            ja_mutou.append(param)
            pm._cache['finance']['C'] = {'type': 'int', 'value': 3}
        return original(param)

    with patch.object(
        ParamManager, '_process_parameter', side_effect=muta_na_primeira_chave
    ):
        resultado = pm.get_all_params('finance')

    assert ja_mutou, 'a mutação concorrente não chegou a ser exercitada'
    assert set(resultado) == {'A', 'B'}


def test_delete_param_nao_muta_o_dict_anterior(setup_param_manager):
    """
    R2: delete_param substitui o dict do cache, não o muta in-place.

    Quem já segurava uma referência ao dict anterior — o merge de
    _save_to_local_db, por exemplo — não pode vê-lo encolher embaixo.
    """
    pm, _, requests_mock = setup_param_manager

    pm._cache['finance'] = {
        'limit': {'type': 'int', 'value': 1},
        'outro': {'type': 'int', 'value': 2},
    }
    pm._cache_timestamp['finance'] = time.time()
    referencia_anterior = pm._cache['finance']

    requests_mock.post(
        'http://test-api.example.com/auth/token',
        json={'access_token': 'TT', 'refresh_token': 'RR'},
        status_code=200,
    )
    requests_mock.delete(
        'http://test-api.example.com/parameters/apps/finance/params/limit',
        json={'status': 'deleted'},
        status_code=200,
    )

    pm.delete_param('finance', 'limit')

    assert pm._cache['finance'] is not referencia_anterior
    assert 'limit' not in pm._cache['finance']
    assert 'limit' in referencia_anterior


def test_publicar_cache_ignora_resposta_atrasada(setup_param_manager):
    """
    R5 (corolário): resposta antiga não sobrescreve cache mais novo.

    Sem o CAS, a resposta atrasada devolveria o app ao dado velho por
    até _cache_duration.
    """
    pm, *_ = setup_param_manager

    recente = time.time()
    atrasada = recente - 30

    pm._publicar_cache('finance', {'novo': {'value': 1}}, recente)
    pm._publicar_cache('finance', {'velho': {'value': 0}}, atrasada)

    assert pm._cache['finance'] == {'novo': {'value': 1}}
    assert pm._cache_timestamp['finance'] == recente


def test_desarmar_breaker_ignora_resposta_atrasada(setup_param_manager):
    """
    R5: sucesso iniciado ANTES do erro não desarma o breaker.

    Sem o CAS, uma resposta em voo desde antes da falha apagaria o
    registro do erro e reabriria o circuito cedo demais.

    A requisição começa 10s antes do erro para que a ordem seja
    inequívoca: no empate exato de timestamp o desarme é o
    comportamento desejado, ver a docstring de _desarmar_breaker.
    """
    pm, *_ = setup_param_manager

    iniciada_em = time.time() - 10
    pm._armar_breaker('finance')

    pm._desarmar_breaker('finance', iniciada_em)
    assert 'finance' in pm._api_error_timestamp

    # Já uma requisição iniciada depois do erro desarma normalmente.
    pm._desarmar_breaker('finance', time.time() + 1)
    assert 'finance' not in pm._api_error_timestamp


def test_clear_cache_desarma_breaker_incondicionalmente(setup_param_manager):
    """
    As duas semânticas sobre _api_error_timestamp são deliberadas.

    clear_cache é ação explícita do operador e desarma sempre; o
    desarme por sucesso é CAS-guardado. Uniformizar as duas reintroduz
    a race do desarme precoce.
    """
    pm, *_ = setup_param_manager

    pm._armar_breaker('finance')
    pm.clear_cache('finance')

    assert 'finance' not in pm._api_error_timestamp