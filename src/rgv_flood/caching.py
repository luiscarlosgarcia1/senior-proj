"""HTTP caching for API responses: an ETag from the body, a 304 when the
browser already holds it, and a Cache-Control lifetime."""

from __future__ import annotations

import hashlib
import json

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder


def etag_for(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'


def _matches(request: Request, etag: str) -> bool:
    sent = request.headers.get("if-none-match", "")
    return etag in {tag.strip() for tag in sent.split(",")} or sent.strip() == "*"


def conditional_json(request: Request, payload, max_age: int) -> Response:
    """`payload` as JSON with an ETag and `Cache-Control: public, max-age=<max_age>`;
    an empty 304 when the request's If-None-Match already names this body."""
    body = json.dumps(jsonable_encoder(payload), separators=(",", ":"), ensure_ascii=False).encode()
    etag = etag_for(body)
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}"}
    if _matches(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
