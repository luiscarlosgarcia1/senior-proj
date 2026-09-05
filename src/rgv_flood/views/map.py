"""Routes for the single-page map and its HTMX partials."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from rgv_flood import data_access
from rgv_flood.counties import COUNTIES, is_county
from rgv_flood.severity import MAPPING, RELATIVE_CLASSES

bp = Blueprint("map", __name__)


@bp.get("/")
def index():
    return render_template(
        "index.html",
        counties=COUNTIES,
        layers=data_access.available_layers(),
        relative_classes=RELATIVE_CLASSES,
        severity_mapping=MAPPING,
    )


@bp.get("/api/layers/<layer_id>.geojson")
def layer(layer_id: str):
    data = data_access.layer_geojson(layer_id)
    if data is None:
        abort(404)
    return jsonify(data)


@bp.get("/partials/metadata/<layer_id>")
def metadata_partial(layer_id: str):
    """Source card shown when a layer or zone is selected."""
    for entry in data_access.available_layers():
        if entry["id"] == layer_id:
            return render_template("partials/metadata.html", layer=entry)
    abort(404)


@bp.get("/partials/closures")
def closures_partial():
    county_slug = request.args.get("county_slug") or None
    if county_slug is not None and not is_county(county_slug):
        abort(404)
    return render_template(
        "partials/closures.html",
        reports=data_access.closure_reports(county_slug),
        county=COUNTIES.get(county_slug) if county_slug else None,
    )
