"""Sign in with a UTRGV Microsoft account.

OpenID Connect authorization-code flow with PKCE against Microsoft Entra, using
the owner's own app registration (set to accept accounts from any organization,
so nothing has to be changed in UTRGV's tenant). A sign-in is accepted only if
the ID token verifies and belongs to UTRGV's tenant and an `@utrgv.edu` account.
Only the `openid profile email` scopes are asked for.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

import httpx2
import jwt

from rgv_flood.chat.session import sign, unsign
from rgv_flood.settings import Settings

AUTHORITY = "https://login.microsoftonline.com"
UTRGV_DOMAIN = "@utrgv.edu"
SCOPES = "openid profile email"
STATE_COOKIE = "rgv_oidc"
STATE_TTL = 600
SESSION_COOKIE = "rgv_session"
SESSION_TTL = 7 * 24 * 3600
KEYS_TTL = 24 * 3600
KEYS_RETRY = 300  # an unknown key id may mean a key rotation: look again, but not more than this often
REFUSED = "That sign-in could not be verified."
FAILED = "Sign-in did not complete. Please try again."


class LoginRefused(Exception):
    """The sign-in was not accepted. The message is safe to show a person."""


def safe_next(value: str | None) -> str:
    """Where to send someone after sign-in: a path on this site, or `/`."""
    if not value or len(value) > 200 or not value.startswith("/"):
        return "/"
    if value[1:2] in ("/", "\\") or "@" in value or "\\" in value or ":" in value.split("?", 1)[0]:
        return "/"
    return value


def verify_id_token(
    token: str, *, jwks: dict, client_id: str, tenant_id: str, nonce: str, now: float | None = None
) -> dict:
    """The token's claims if it is a good UTRGV sign-in; otherwise LoginRefused."""
    now = time.time() if now is None else now
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise LoginRefused(REFUSED)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
        if key is None:
            raise LoginRefused(REFUSED)
        claims = jwt.decode(
            token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"], audience=client_id,
            issuer=f"{AUTHORITY}/{tenant_id}/v2.0",
            options={"require": ["exp", "iss", "aud"], "verify_exp": False, "verify_iat": False, "verify_nbf": False},
        )
    except jwt.PyJWTError:
        raise LoginRefused(REFUSED) from None
    if not isinstance(claims.get("exp"), int | float) or claims["exp"] <= now:
        raise LoginRefused(REFUSED)
    if claims.get("tid") != tenant_id:
        raise LoginRefused(REFUSED)
    if not hmac.compare_digest(str(claims.get("nonce", "")).encode(), nonce.encode()):
        raise LoginRefused(REFUSED)
    username = str(claims.get("preferred_username") or "").lower()
    if not username.endswith(UTRGV_DOMAIN) or len(username) <= len(UTRGV_DOMAIN) or " " in username:
        raise LoginRefused(REFUSED)
    return claims


class MicrosoftLogin:
    def __init__(self, settings: Settings, *, transport=None):
        self.client_id = settings.ms_client_id
        self.client_secret = settings.ms_client_secret.get_secret_value()
        self.tenant_id = settings.ms_tenant_id
        self.redirect_uri = f"{settings.public_url.rstrip('/')}/auth/callback"
        self.session_secret = settings.session_secret.get_secret_value()
        self.client = httpx2.Client(transport=transport, timeout=10.0)
        self._keys_cache: dict | None = None
        self._keys_fetched = 0.0

    def begin(self, next_url: str) -> tuple[str, str]:
        """(the Microsoft address to send the browser to, the signed cookie that remembers this attempt)."""
        state, nonce, verifier = secrets.token_urlsafe(16), secrets.token_urlsafe(16), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "response_mode": "query", "scope": SCOPES, "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        cookie = sign({"state": state, "nonce": nonce, "verifier": verifier, "next": safe_next(next_url)},
                      self.session_secret, STATE_TTL)
        return f"{AUTHORITY}/{self.tenant_id}/oauth2/v2.0/authorize?{query}", cookie

    def _keys(self, wanted_kid: str | None = None) -> dict:
        age = time.monotonic() - self._keys_fetched
        have = self._keys_cache
        known = have is not None and (wanted_kid is None or any(k.get("kid") == wanted_kid for k in have.get("keys", [])))
        if have is not None and age < KEYS_TTL and (known or age < KEYS_RETRY):
            return have
        try:
            response = self.client.get(f"{AUTHORITY}/{self.tenant_id}/discovery/v2.0/keys")
            response.raise_for_status()
            self._keys_cache = response.json()
            self._keys_fetched = time.monotonic()
        except (httpx2.HTTPError, ValueError):
            raise LoginRefused(FAILED) from None
        return self._keys_cache

    def finish(self, code: str, state: str, state_cookie: str) -> tuple[str, str]:
        """Exchange the code for a token and check it: (the account's email, where to go next)."""
        attempt = unsign(state_cookie, self.session_secret) if state_cookie else None
        if not attempt or not hmac.compare_digest(str(state).encode(), str(attempt.get("state", "")).encode()):
            raise LoginRefused(REFUSED)
        try:
            response = self.client.post(f"{AUTHORITY}/{self.tenant_id}/oauth2/v2.0/token", data={
                "client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code",
                "code": code, "redirect_uri": self.redirect_uri, "code_verifier": attempt["verifier"],
            })
            response.raise_for_status()
            id_token = response.json()["id_token"]
            if not isinstance(id_token, str):
                raise TypeError("id_token is not text")
        except (httpx2.HTTPError, ValueError, KeyError, TypeError):
            raise LoginRefused(FAILED) from None
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
        except jwt.PyJWTError:
            raise LoginRefused(REFUSED) from None
        claims = verify_id_token(
            id_token, jwks=self._keys(kid), client_id=self.client_id, tenant_id=self.tenant_id, nonce=attempt["nonce"]
        )
        return str(claims["preferred_username"]).lower(), safe_next(attempt.get("next"))
