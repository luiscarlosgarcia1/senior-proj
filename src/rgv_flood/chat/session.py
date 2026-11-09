"""Signed, expiring values for cookies: `payload.signature`, both URL-safe base64.

The payload is readable by whoever holds the cookie but cannot be changed or
moved to another secret without the signature failing. Nothing secret goes in it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def sign(payload: dict, secret: str, ttl_seconds: int, *, now: float | None = None) -> str:
    """`payload` as a cookie value that stops working `ttl_seconds` from `now`."""
    expires = (time.time() if now is None else now) + ttl_seconds
    body = _b64(json.dumps({**payload, "_exp": expires}, separators=(",", ":")).encode())
    return f"{body}.{_signature(body, secret)}"


def unsign(token: str, secret: str, *, now: float | None = None) -> dict | None:
    """The payload if the signature is good and the value has not expired; otherwise None."""
    try:
        body, signature = token.split(".")
        if not hmac.compare_digest(signature.encode("ascii"), _signature(body, secret).encode("ascii")):
            return None
        data = json.loads(_unb64(body))
        if not isinstance(data, dict) or float(data.pop("_exp")) <= (time.time() if now is None else now):
            return None
        return data
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None
