"""API: /auth/login, /auth/callback and /auth/logout (Microsoft is faked; nothing leaves the machine)."""

from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from rgv_flood.chat.microsoft import SESSION_COOKIE, STATE_COOKIE, MicrosoftLogin
from rgv_flood.chat.session import unsign
from rgv_flood.settings import Settings

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "client-id"
SECRET = "s" * 40
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def settings_for(database, tmp_path, public_url="http://site.test"):
    return {
        "database": database, "live_signals_scheduler_enabled": False, "chat_usage_database": tmp_path / "usage.sqlite3",
        "azure_openai_endpoint": "https://az.test", "azure_openai_api_key": "SECRET-TEST-KEY", "azure_openai_deployment": "d",
        "session_secret": SECRET, "ms_client_id": CLIENT, "ms_client_secret": "CLIENT-SECRET-VALUE", "ms_tenant_id": TENANT,
        "public_url": public_url,
    }


def fake_microsoft(client, settings, nonce_of=None, username="ana@utrgv.edu", tenant=TENANT):
    """Point the app's sign-in at a pretend Microsoft that issues a token for `username`."""
    jwk = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k", "use": "sig"}

    def handler(request):
        if request.url.path.endswith("/keys"):
            return httpx2.Response(200, json={"keys": [jwk]})
        nonce = unsign(client.cookies[STATE_COOKIE], SECRET)["nonce"]
        text = jwt.encode(
            {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": CLIENT, "tid": tenant,
             "exp": 4_000_000_000, "nonce": nonce, "preferred_username": username},
            KEY, algorithm="RS256", headers={"kid": "k"},
        )
        return httpx2.Response(200, json={"id_token": text})

    client.app.state.chat.login = MicrosoftLogin(Settings(**settings), transport=httpx2.MockTransport(handler))


@pytest.fixture()
def app_client(make_client, fixture_db, tmp_path):
    settings = settings_for(fixture_db, tmp_path)
    client = make_client(fixture_db, **{k: v for k, v in settings.items() if k not in ("database", "live_signals_scheduler_enabled")})
    return client, settings


def test_login_redirects_to_microsoft_and_sets_a_state_cookie(app_client):
    client, _ = app_client

    response = client.get("/auth/login?next=/map", follow_redirects=False)

    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.netloc == "login.microsoftonline.com" and location.path.startswith(f"/{TENANT}/oauth2/v2.0/authorize")
    assert parse_qs(location.query)["client_id"] == [CLIENT]
    cookie = response.headers["set-cookie"].lower()
    assert STATE_COOKIE in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_the_state_cookie_is_secure_on_an_https_site(make_client, fixture_db, tmp_path):
    settings = settings_for(fixture_db, tmp_path, public_url="https://site.test")
    client = make_client(fixture_db, **{k: v for k, v in settings.items() if k not in ("database", "live_signals_scheduler_enabled")})

    response = client.get("/auth/login", follow_redirects=False)

    assert "secure" in response.headers["set-cookie"].lower()


def test_callback_sets_a_signed_session_cookie_and_goes_on(app_client):
    client, settings = app_client
    client.get("/auth/login?next=/claims", follow_redirects=False)
    fake_microsoft(client, settings)
    state = unsign(client.cookies[STATE_COOKIE], SECRET)["state"]

    response = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert response.status_code == 302 and response.headers["location"] == "/claims"
    assert unsign(client.cookies[SESSION_COOKIE], SECRET) == {"email": "ana@utrgv.edu"}
    assert STATE_COOKIE not in client.cookies  # one attempt, one cookie


def test_an_evil_next_still_lands_on_the_home_page(app_client):
    client, settings = app_client
    client.get("/auth/login?next=//evil.test", follow_redirects=False)
    fake_microsoft(client, settings)
    state = unsign(client.cookies[STATE_COOKIE], SECRET)["state"]

    response = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert response.headers["location"] == "/"


def test_a_wrong_state_is_refused_and_sets_no_session(app_client):
    client, settings = app_client
    client.get("/auth/login", follow_redirects=False)
    fake_microsoft(client, settings)

    response = client.get("/auth/callback?code=abc&state=not-the-state", follow_redirects=False)

    assert response.headers["location"] == "/?signin=failed"
    assert SESSION_COOKIE not in client.cookies


def test_a_callback_with_no_login_attempt_is_refused(app_client):
    client, _ = app_client

    response = client.get("/auth/callback?code=abc&state=x", follow_redirects=False)

    assert response.headers["location"] == "/?signin=failed"


@pytest.mark.parametrize("username, tenant", [("ana@gmail.com", TENANT), ("ana@utrgv.edu", "99999999-0000-0000-0000-000000000000")])
def test_a_token_for_the_wrong_account_or_tenant_gives_no_session(app_client, username, tenant):
    client, settings = app_client
    client.get("/auth/login", follow_redirects=False)
    fake_microsoft(client, settings, username=username, tenant=tenant)
    state = unsign(client.cookies[STATE_COOKIE], SECRET)["state"]

    response = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert response.headers["location"] == "/?signin=failed" and SESSION_COOKIE not in client.cookies


def test_callback_with_a_microsoft_error_goes_home_with_a_flag(app_client):
    client, _ = app_client

    response = client.get("/auth/callback?error=access_denied&error_description=nope", follow_redirects=False)

    assert response.headers["location"] == "/?signin=failed"


def test_logout_clears_the_cookie(app_client):
    client, settings = app_client
    client.get("/auth/login", follow_redirects=False)
    fake_microsoft(client, settings)
    client.get(f"/auth/callback?code=abc&state={unsign(client.cookies[STATE_COOKIE], SECRET)['state']}", follow_redirects=False)
    assert SESSION_COOKIE in client.cookies

    response = client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 302 and response.headers["location"] == "/"
    assert SESSION_COOKIE not in client.cookies


def test_auth_routes_are_404_when_sign_in_is_not_set_up(api_client):
    for path in ("/auth/login", "/auth/callback?code=a&state=b", "/auth/logout"):
        assert api_client.get(path, follow_redirects=False).status_code == 404


def test_auth_routes_are_404_when_chat_is_on_but_sign_in_is_not(make_client, fixture_db, tmp_path):
    settings = settings_for(fixture_db, tmp_path)
    for field in ("ms_client_id", "ms_client_secret", "ms_tenant_id", "public_url"):
        settings.pop(field)
    client = make_client(fixture_db, **{k: v for k, v in settings.items() if k not in ("database", "live_signals_scheduler_enabled")})

    assert client.get("/auth/login", follow_redirects=False).status_code == 404
