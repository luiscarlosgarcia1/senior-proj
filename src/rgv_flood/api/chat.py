"""/api/v1/chat: ask the data assistant a question.

The one POST in the API, and it only ever reads the data. Each message is
counted against the visitor's daily allowance before the model is called, and
given back if the model could not answer. Errors never carry the model's
reply, a stack trace or a secret.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rgv_flood.api.models import ChatRequest, ChatResponse, ChatStatus
from rgv_flood.chat.agent import ModelUnavailable, run_agent
from rgv_flood.chat.limits import ANON_DAILY, ANON_IP_DAILY, SIGNED_IN_DAILY
from rgv_flood.chat.microsoft import SESSION_COOKIE, UTRGV_DOMAIN
from rgv_flood.chat.service import ChatService
from rgv_flood.chat.session import sign, unsign

router = APIRouter()
logger = logging.getLogger(__name__)

VISITOR_COOKIE = "rgv_visitor"
VISITOR_TTL = 365 * 24 * 3600
NOT_SET_UP = "The chat is not set up on this server."
UNAVAILABLE = "The assistant is unavailable right now. Try again in a moment."
FAILED = "Something went wrong answering that. Try again in a moment."


@dataclass
class Visitor:
    """Who is asking and what they are allowed: `limits` maps each counted key to its daily limit."""

    limits: dict[str, int]
    limit: int
    signed_in: bool
    email: str | None = None
    new_cookie: str | None = field(default=None, repr=False)


def identify(request: Request, service: ChatService) -> Visitor:
    secret = service.settings.session_secret.get_secret_value()
    session = unsign(request.cookies.get(SESSION_COOKIE, ""), secret)
    email = session.get("email") if session else None
    if isinstance(email, str) and email.lower().endswith(UTRGV_DOMAIN):
        return Visitor(limits={f"u:{email.lower()}": SIGNED_IN_DAILY}, limit=SIGNED_IN_DAILY, signed_in=True, email=email.lower())
    held = unsign(request.cookies.get(VISITOR_COOKIE, ""), secret)
    visitor_id, new_cookie = held.get("id") if held else None, None
    if not isinstance(visitor_id, str) or not visitor_id:
        visitor_id = secrets.token_hex(16)
        new_cookie = sign({"id": visitor_id}, secret, VISITOR_TTL)
    address = request.client.host if request.client else "unknown"
    limits = {f"v:{visitor_id}": ANON_DAILY, f"ip:{address}": ANON_IP_DAILY}
    return Visitor(limits=limits, limit=ANON_DAILY, signed_in=False, new_cookie=new_cookie)


def remaining(service: ChatService, visitor: Visitor) -> int:
    return max(0, min(limit - service.usage.used(key) for key, limit in visitor.limits.items()))


def respond(request: Request, service: ChatService | None, visitor: Visitor | None, status: int, content: dict) -> JSONResponse:
    response = JSONResponse(content, status_code=status, headers={"Cache-Control": "no-store"})
    if visitor and visitor.new_cookie:
        response.set_cookie(
            VISITOR_COOKIE, visitor.new_cookie, max_age=VISITOR_TTL, httponly=True, samesite="lax", path="/",
            secure=bool(service) and service.settings.public_url.startswith("https://"),
        )
    return response


@router.post("/chat", response_model=ChatResponse)
def chat(request: Request, body: ChatRequest):
    service: ChatService | None = request.app.state.chat
    if service is None:
        return respond(request, None, None, 503, {"detail": NOT_SET_UP})
    visitor = identify(request, service)
    if not service.usage.try_consume(visitor.limits):
        detail = f"You have used today's {ANON_DAILY} messages." if not visitor.signed_in else "You have reached today's limit."
        offer_login = service.login is not None and not visitor.signed_in
        if offer_login:
            detail += " Sign in with your UTRGV account to keep asking."
        return respond(request, service, visitor, 429, {"detail": detail, "signin": offer_login})
    try:
        result = run_agent(service.model, service.db, [turn.model_dump() for turn in body.history], body.message)
    except ModelUnavailable:
        service.usage.refund(list(visitor.limits))
        return respond(request, service, visitor, 502, {"detail": UNAVAILABLE})
    except Exception as error:  # noqa: BLE001 - any failure refunds the message; only the type is logged, as the text could carry a secret
        logger.error("chat failed: %s", type(error).__name__)
        service.usage.refund(list(visitor.limits))
        return respond(request, service, visitor, 500, {"detail": FAILED})
    answer = ChatResponse(answer=result.answer, remaining=remaining(service, visitor), limit=visitor.limit, signed_in=visitor.signed_in)
    return respond(request, service, visitor, 200, answer.model_dump())


@router.get("/chat/status", response_model=ChatStatus)
def status(request: Request):
    service: ChatService | None = request.app.state.chat
    if service is None:
        return respond(request, None, None, 200, ChatStatus(enabled=False, login_enabled=False, signed_in=False).model_dump())
    visitor = identify(request, service)
    body = ChatStatus(
        enabled=True, login_enabled=service.login is not None, signed_in=visitor.signed_in, email=visitor.email,
        remaining=remaining(service, visitor), limit=visitor.limit,
    )
    return respond(request, service, visitor, 200, body.model_dump())
