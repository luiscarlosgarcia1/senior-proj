"""/auth/*: sign in with a UTRGV Microsoft account (see rgv_flood/chat/microsoft.py).

These are ordinary browser pages (redirects), not part of the JSON API, so they
live at the site root. All three answer 404 unless sign-in is set up.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from rgv_flood.chat.microsoft import (
    SESSION_COOKIE,
    SESSION_TTL,
    STATE_COOKIE,
    STATE_TTL,
    LoginRefused,
)
from rgv_flood.chat.service import ChatService
from rgv_flood.chat.session import sign

router = APIRouter()
STATE_PATH = "/auth"


def _service(request: Request) -> ChatService:
    service = request.app.state.chat
    if service is None or service.login is None:
        raise HTTPException(404)
    return service


def _secure(service: ChatService) -> bool:
    return service.settings.public_url.startswith("https://")


@router.get("/auth/login", include_in_schema=False)
def login(request: Request, next: str = "/"):
    service = _service(request)
    url, cookie = service.login.begin(next)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(STATE_COOKIE, cookie, max_age=STATE_TTL, httponly=True, samesite="lax",
                        secure=_secure(service), path=STATE_PATH)
    return response


@router.get("/auth/callback", include_in_schema=False)
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    service = _service(request)
    response = RedirectResponse("/?signin=failed", status_code=302)
    if not error and code and state:
        try:
            email, next_url = service.login.finish(code, state, request.cookies.get(STATE_COOKIE, ""))
        except LoginRefused:
            pass
        else:
            response = RedirectResponse(next_url, status_code=302)
            response.set_cookie(
                SESSION_COOKIE, sign({"email": email}, service.settings.session_secret.get_secret_value(), SESSION_TTL),
                max_age=SESSION_TTL, httponly=True, samesite="lax", secure=_secure(service), path="/",
            )
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return response


@router.get("/auth/logout", include_in_schema=False)
def logout(request: Request):
    _service(request)
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
