"""Tests de autenticación con Flask-Login (HC2 Día 2)."""


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_login_get_renderiza(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_login_credenciales_validas_redirige(client, facilitador):
    resp = _login(client)
    assert resp.status_code == 302


def test_login_email_inexistente_falla(client, facilitador):
    resp = _login(client, email="nadie@fuenti.cl")
    # Login fallido redirige de vuelta a /login (patrón Post-Redirect-Get con flash)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_password_incorrecta_falla(client, facilitador):
    resp = _login(client, password="password-malo")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dashboard_sin_auth_redirige_a_login(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dashboard_con_auth_responde_200(client, facilitador):
    _login(client)
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_logout_redirige(client, facilitador):
    _login(client)
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302