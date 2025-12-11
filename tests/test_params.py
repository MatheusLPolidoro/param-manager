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
