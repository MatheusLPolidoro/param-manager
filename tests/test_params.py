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
    assert pm._is_api_error_cached("finance")


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
