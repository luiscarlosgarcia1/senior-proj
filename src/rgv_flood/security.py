"""Security headers on every response, including a strict content-security policy.

Scripts, styles and fonts come only from this app (third-party libraries are
vendored). The map's basemap comes from OpenFreeMap; photos come from the
Hidalgo drainage district's ArcGIS server and from Wikimedia. MapLibre runs its
workers from blob: URLs. Plotly inserts <style> elements, hence
'unsafe-inline' for styles only.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def content_security_policy(inline_script_hashes: list[str] | tuple[str, ...] = ()) -> str:
    scripts = " ".join(["'self'", *(f"'{h}'" for h in inline_script_hashes)])
    return "; ".join([
        "default-src 'self'",
        f"script-src {scripts}",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://services7.arcgis.com https://*.wikimedia.org",
        "font-src 'self'",
        "connect-src 'self' https://tiles.openfreemap.org",
        "worker-src 'self' blob:",
        "child-src blob:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ])


class SecurityHeadersMiddleware:
    """Adds the headers to every response that doesn't set its own (plain ASGI,
    so response bodies stream through untouched)."""

    def __init__(self, app: ASGIApp, inline_script_hashes: list[str] | tuple[str, ...] = ()) -> None:
        self.app = app
        self.headers = {
            "Content-Security-Policy": content_security_policy(inline_script_hashes),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
