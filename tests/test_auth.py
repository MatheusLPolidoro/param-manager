def test_get_token(setup_param_manager):
    pm, _, requests_mock = setup_param_manager

    requests_mock.post(
        "http://test-api.example.com/auth/token",
        json={"access_token": "AAA", "refresh_token": "BBB"},
        status_code=200,
    )

    token = pm._get_valid_token()

    assert token == "AAA"
    assert pm._refresh_token == "BBB"
    assert pm._token_expire_at > 0


def test_refresh_token(setup_param_manager):
    pm, _, requests_mock = setup_param_manager

    # força token expirado
    pm._token = "OLD"
    pm._refresh_token = "REFRESH_123"
    pm._token_expire_at = 0

    requests_mock.post(
        "http://test-api.example.com/auth/refresh",
        json={"access_token": "NEW", "refresh_token": "NEW_R"},
        status_code=200,
    )

    token = pm._get_valid_token()

    assert token == "NEW"
    assert pm._refresh_token == "NEW_R"
