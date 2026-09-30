"""RGV Flood Impact Visualizer — Flask application factory."""

from __future__ import annotations

import os
import sys

import jinja_partials
from flask import Flask

# live_signals_scheduler.py's advisory lock uses fcntl, POSIX-only (that's
# what runs it on Mac/Linux); Windows gets the msvcrt-based counterpart. Same
# public API either way, so nothing past this import needs to care which.
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


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object("rgv_flood.config.Default")
    if config:
        app.config.from_mapping(config)

    jinja_partials.register_extensions(app)

    from rgv_flood.views.map import bp as map_bp

    app.register_blueprint(map_bp)

    _start_live_signal_scheduler(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _start_live_signal_scheduler(app: Flask) -> None:
    """Start one background refresher, excluding Werkzeug's reload parent."""
    if not app.config["LIVE_SIGNALS_SCHEDULER_ENABLED"]:
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    scheduler = LiveSignalScheduler(
        build_refresh_commands(app.config["LIVE_SIGNALS_DATABASE"]),
        interval_seconds=app.config["LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS"],
        lock_file=app.config["LIVE_SIGNALS_SCHEDULER_LOCK_FILE"],
    )
    scheduler.start()
    app.extensions["live_signals_scheduler"] = scheduler
