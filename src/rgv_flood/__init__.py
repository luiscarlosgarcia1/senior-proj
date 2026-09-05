"""RGV Flood Impact Visualizer — Flask application factory."""

from __future__ import annotations

import jinja_partials
from flask import Flask


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object("rgv_flood.config.Default")
    if config:
        app.config.from_mapping(config)

    jinja_partials.register_extensions(app)

    from rgv_flood.views.map import bp as map_bp

    app.register_blueprint(map_bp)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
