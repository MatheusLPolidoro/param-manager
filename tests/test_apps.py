def test_create_app(setup_param_manager):
    pm, _, requests_mock = setup_param_manager

    # mock token
    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "TOK", "refresh_token": "RT"},
        status_code=200,
    )

    # mock endpoint
    requests_mock.post(
        "http://test-api.example.com/parameters/apps/",
        json={"name": "finance", "description": "desc"},
        status_code=201,
    )

    res = pm.create_app("finance", "desc")
    assert res["name"] == "finance"


def test_delete_app(setup_param_manager):
    pm, _, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "X", "refresh_token": "Y"},
        status_code=200,
    )

    requests_mock.delete(
        "http://test-api.example.com/parameters/apps/finance",
        json={"status": "ok"},
        status_code=200,
    )

    res = pm.delete_app("finance")
    assert res["status"] == "ok"
