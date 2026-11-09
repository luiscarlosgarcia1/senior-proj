"""Chat: checking a Microsoft sign-in (rgv_flood/chat/microsoft.py). Every token here is made locally."""

import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from rgv_flood.chat.microsoft import (
    LoginRefused,
    MicrosoftLogin,
    safe_next,
    verify_id_token,
)
from rgv_flood.chat.session import sign, unsign
from rgv_flood.settings import Settings

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "client-id"
NOW = 1_800_000_000.0
KID = "key-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SECRET = "s" * 40


def jwks(key=KEY, kid=KID):
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "use": "sig"}]}


def claims(**changes):
    base = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": CLIENT, "tid": TENANT,
        "exp": NOW + 3600, "iat": NOW, "nonce": "n1", "preferred_username": "ana@utrgv.edu",
    }
    return {key: value for key, value in {**base, **changes}.items() if value is not None}


def token(key=KEY, **changes):
    return jwt.encode(claims(**changes), key, algorithm="RS256", headers={"kid": KID})


def verify(text, **overrides):
    arguments = {"jwks": jwks(), "client_id": CLIENT, "tenant_id": TENANT, "nonce": "n1", "now": NOW, **overrides}
    return verify_id_token(text, **arguments)


def test_good_token_is_accepted():
    assert verify(token())["preferred_username"] == "ana@utrgv.edu"


def test_uppercase_domain_is_accepted():
    assert verify(token(preferred_username="Ana@UTRGV.EDU"))["preferred_username"] == "Ana@UTRGV.EDU"


@pytest.mark.parametrize("make", [
    lambda: token(key=OTHER_KEY),  # signed by someone else's key
    lambda: token(iss="https://login.microsoftonline.com/other/v2.0"),
    lambda: token(aud="someone-elses-app"),
    lambda: token(tid="99999999-0000-0000-0000-000000000000"),
    lambda: token(exp=NOW - 10),
    lambda: token(nonce="not-the-nonce"),
    lambda: token(preferred_username="ana@utrgv.edu.evil.test"),
    lambda: token(preferred_username="x@notutrgv.edu"),
    lambda: token(preferred_username="@utrgv.edu"),
    lambda: token(preferred_username=None),
    lambda: "not-a-token",
    lambda: "",
], ids=["wrong-key", "issuer", "audience", "tenant", "expired", "nonce", "suffix-domain", "other-domain",
        "no-local-part", "no-username", "garbage", "empty"])
def test_bad_tokens_are_refused_without_echoing_them(make):
    text = make()

    with pytest.raises(LoginRefused) as raised:
        verify(text)

    assert not text or text not in str(raised.value)


def test_unsigned_alg_none_token_is_refused():
    text = jwt.encode(claims(), None, algorithm="none", headers={"kid": KID})

    with pytest.raises(LoginRefused):
        verify(text)


def test_hs256_token_signed_with_the_public_key_is_refused():
    """The classic algorithm-confusion attack: HMAC-sign with the public key as the secret."""
    public_pem = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=")
    head = b64(json.dumps({"alg": "HS256", "kid": KID, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims()).encode())
    forged = b".".join([head, body, b64(hmac.new(public_pem, head + b"." + body, hashlib.sha256).digest())]).decode()

    with pytest.raises(LoginRefused):
        verify(forged)


def test_unknown_key_id_is_refused():
    with pytest.raises(LoginRefused):
        verify(token(), jwks=jwks(kid="another-key"))


@pytest.mark.parametrize("value, expected", [
    ("/map", "/map"), ("/claims?x=1", "/claims?x=1"), ("/", "/"),
    ("//evil.test", "/"), ("https://evil.test", "/"), ("/\\evil.test", "/"), ("javascript:alert(1)", "/"),
    ("", "/"), (None, "/"), ("/" + "a" * 300, "/"), ("/a@b", "/"), ("map", "/"),
])
def test_safe_next(value, expected):
    assert safe_next(value) == expected


# ---- the sign-in flow, with Microsoft's two endpoints faked ----

SETTINGS = Settings(
    azure_openai_endpoint="https://az.test", azure_openai_api_key="SECRET-TEST-KEY", azure_openai_deployment="d",
    session_secret=SECRET, ms_client_id=CLIENT, ms_client_secret="CLIENT-SECRET-VALUE", ms_tenant_id=TENANT,
    public_url="https://site.test",
)


def login(handler, calls=None):
    def record(request):
        if calls is not None:
            calls.append(request)
        return handler(request)

    return MicrosoftLogin(SETTINGS, transport=httpx2.MockTransport(record))


def microsoft(id_token):
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx2.Response(200, json={"id_token": id_token, "access_token": "unused"})
        return httpx2.Response(200, json=jwks())

    return handler


def test_begin_builds_a_pkce_authorize_url():
    url, cookie = login(microsoft("x")).begin("/map")

    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
    assert query["client_id"] == CLIENT and query["response_type"] == "code"
    assert query["redirect_uri"] == "https://site.test/auth/callback"
    assert query["scope"] == "openid profile email" and query["code_challenge_method"] == "S256"
    held = unsign(cookie, SECRET, now=None)
    assert held["next"] == "/map" and held["state"] == query["state"] and held["nonce"] == query["nonce"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(held["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == challenge
    assert held["verifier"] not in url  # only its hash goes to Microsoft


def test_begin_cleans_an_evil_next():
    _, cookie = login(microsoft("x")).begin("//evil.test")

    assert unsign(cookie, SECRET)["next"] == "/"


def test_finish_happy_path():
    flow = login(None)
    _, cookie = flow.begin("/map")
    held = unsign(cookie, SECRET)
    flow = login(microsoft(token(nonce=held["nonce"])))

    email, next_url = flow.finish("the-code", held["state"], cookie)

    assert (email, next_url) == ("ana@utrgv.edu", "/map")


def test_finish_sends_the_verifier_and_secret_to_the_token_endpoint_only():
    calls = []
    _, cookie = login(None).begin("/")
    held = unsign(cookie, SECRET)
    flow = login(microsoft(token(nonce=held["nonce"])), calls)

    flow.finish("the-code", held["state"], cookie)

    (exchange,) = [c for c in calls if c.url.path.endswith("/token")]
    form = parse_qs(exchange.content.decode())
    assert form["code"] == ["the-code"] and form["code_verifier"] == [held["verifier"]]
    assert form["client_secret"] == ["CLIENT-SECRET-VALUE"] and form["grant_type"] == ["authorization_code"]
    assert all("CLIENT-SECRET-VALUE" not in str(c.url) for c in calls)


def test_finish_refuses_state_mismatch_and_missing_or_forged_cookie():
    _, cookie = login(None).begin("/")
    held = unsign(cookie, SECRET)
    flow = login(microsoft(token(nonce=held["nonce"])))

    for state, state_cookie in ((held["state"] + "x", cookie), (held["state"], ""), (held["state"], "garbage"),
                                (held["state"], sign(held, "t" * 40, 600))):
        with pytest.raises(LoginRefused):
            flow.finish("code", state, state_cookie)


def test_finish_refuses_an_expired_state_cookie():
    expired = sign({"state": "s", "nonce": "n1", "verifier": "v", "next": "/"}, SECRET, 600, now=1.0)

    with pytest.raises(LoginRefused):
        login(microsoft(token())).finish("code", "s", expired)


def test_finish_refuses_when_the_token_endpoint_fails_and_hides_the_secret():
    _, cookie = login(None).begin("/")
    held = unsign(cookie, SECRET)
    flow = login(lambda request: httpx2.Response(400, json={"error": "invalid_grant", "echo": "CLIENT-SECRET-VALUE"}))

    with pytest.raises(LoginRefused) as raised:
        flow.finish("code", held["state"], cookie)

    assert "CLIENT-SECRET-VALUE" not in str(raised.value) and "invalid_grant" not in str(raised.value)


def test_finish_refuses_a_token_for_another_tenant():
    _, cookie = login(None).begin("/")
    held = unsign(cookie, SECRET)
    flow = login(microsoft(token(nonce=held["nonce"], tid="99999999-0000-0000-0000-000000000000")))

    with pytest.raises(LoginRefused):
        flow.finish("code", held["state"], cookie)


def test_signing_keys_are_fetched_once():
    calls = []
    current = {}
    flow = login(lambda request: microsoft(token(nonce=current["nonce"]))(request), calls)

    for _ in range(2):
        _, cookie = flow.begin("/")
        held = unsign(cookie, SECRET)
        current["nonce"] = held["nonce"]
        flow.finish("code", held["state"], cookie)

    assert len([c for c in calls if c.url.path.endswith("/keys")]) == 1
