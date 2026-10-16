"""The RGV Flood Impact Visualizer as one FastAPI service: pages, the JSON API,
vector tiles and static files, plus the background live-alert refresher.

Run:  uv run dev          (development, auto-reload)
      uv run serve        (production)
"""

from __future__ import annotations

import json
import logging
import mimetypes
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware

from rgv_flood.api import api_router, geocode
from rgv_flood.api import health as health_api
from rgv_flood.assets import STATIC_ROOT, VersionedStaticFiles
from rgv_flood.db import Database
from rgv_flood.security import SecurityHeadersMiddleware
from rgv_flood.settings import Settings, get_settings

# live_signals_scheduler.py's advisory lock uses fcntl, POSIX-only; Windows gets
# the msvcrt-based twin with the same interface.
if sys.platform == "win32":
    from rgv_flood.live_signals_scheduler_windows import (
        LiveSignalScheduler,
        build_refresh_commands,
    )
else:
    from rgv_flood.live_signals_scheduler import (
        LiveSignalScheduler,
        build_refresh_commands,
    )

PACKAGE = Path(__file__).parent

# Windows can map .js to text/plain in the registry; module scripts must be JS.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
access_log = logging.getLogger("rgv_flood.access")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        try:
            payload = json.loads(message)
        except ValueError:
            payload = {"message": message}
        return json.dumps({"level": record.levelname, "logger": record.name, **payload})


def configure_logging(level: str) -> None:
    """One JSON object per line on stderr."""
    root = logging.getLogger()
    if not any(isinstance(h.formatter, _JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)


def _start_scheduler(app: FastAPI, settings: Settings) -> None:
    if not settings.live_signals_scheduler_enabled:
        return
    scheduler = LiveSignalScheduler(
        build_refresh_commands(settings.database),
        interval_seconds=settings.live_signals_refresh_interval_seconds,
        lock_file=settings.live_signals_scheduler_lock_file,
    )
    scheduler.start()
    app.state.live_signals_scheduler = scheduler


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Every worker tries; the scheduler's file lock lets one per host run.
        _start_scheduler(app, settings)
        yield

    app = FastAPI(title="RGV Flood Impact Visualizer", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database)
    geocode.install(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        access_log.info(json.dumps({
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }))
        return response

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_api.router)
    app.include_router(api_router)
    app.mount("/static", VersionedStaticFiles(directory=STATIC_ROOT), name="static")
    return app
