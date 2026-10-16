"""Static assets: content-versioned URLs, the static file mount, the CSS build.

`asset_url("css/app.css")` gives `/static/css/app.css?v=<content hash>`. A URL
with `?v=` never changes meaning, so it is cached for a year; anything else is
revalidated. The stylesheet is compiled ahead of time by Tailwind's standalone
binary (through pytailwindcss, so no Node), from `static/css/input.css`.
"""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

from starlette.staticfiles import StaticFiles

STATIC_ROOT = Path(__file__).parent / "static"
CSS_INPUT = STATIC_ROOT / "css" / "input.css"
CSS_OUTPUT = STATIC_ROOT / "css" / "site.css"  # (app.css is the old Flask app's stylesheet)
TAILWIND_VERSION = "v4.3.3"


@lru_cache
def asset_url(path: str) -> str:
    """The URL of a static file, versioned by its content (unversioned if missing)."""
    file = STATIC_ROOT / path
    if not file.is_file():
        return f"/static/{path}"
    return f"/static/{path}?v={hashlib.sha256(file.read_bytes()).hexdigest()[:10]}"


class VersionedStaticFiles(StaticFiles):
    """Static files; versioned URLs are immutable, others always revalidated."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        versioned = b"v=" in scope.get("query_string", b"")
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "no-cache"
        return response


def tailwind_binary() -> Path:
    """Tailwind's standalone binary at the pinned version, downloaded once.
    (A development and build-time tool: the running app never imports it.)"""
    import pytailwindcss

    binary = pytailwindcss.get_bin_path(TAILWIND_VERSION)
    if not binary.exists():
        pytailwindcss.install(TAILWIND_VERSION, binary)
    return binary


def tailwind_command(output: Path = CSS_OUTPUT, *, minify: bool = True, watch: bool = False) -> list[str]:
    command = [str(tailwind_binary()), "-i", str(CSS_INPUT), "-o", str(output)]
    return command + (["--minify"] if minify else []) + (["--watch"] if watch else [])


def build_css(output: Path = CSS_OUTPUT, *, minify: bool = True) -> Path:
    """Compile the stylesheet once."""
    subprocess.run(tailwind_command(output, minify=minify), check=True, capture_output=True)
    asset_url.cache_clear()
    return output
