"""Routes for the single-page map and its HTMX partials."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from rgv_flood import data_access
from rgv_flood.counties import COUNTIES, is_county
from rgv_flood.severity import RELATIVE_CLASSES

bp = Blueprint("map", __name__)


def _county_arg() -> tuple[str | None, dict | None]:
    """The ?county_slug= filter (None for all counties) and that county's details."""
    slug = request.args.get("county_slug") or None
    if slug is not None and not is_county(slug):
        abort(404)
    return slug, COUNTIES.get(slug)


@bp.get("/")
def index():
    return render_template(
        "index.html",
        counties=COUNTIES,
        layers=data_access.available_layers(),
        relative_classes=RELATIVE_CLASSES,
        event_count=len(data_access.flood_events()),
    )


@bp.get("/api/layers/<layer_id>.geojson")
def layer(layer_id: str):
    path = data_access.layer_path(layer_id)
    if path is None:
        abort(404)
    # The pipeline already wrote valid GeoJSON; send the file as is (with
    # ETag/Last-Modified, so browsers revalidate instead of re-downloading).
    return send_file(path, mimetype="application/json")


@bp.get("/api/flood-events.geojson")
def flood_events_geojson():
    fc = data_access.flood_events_fc()
    if fc is None:
        abort(404)
    return jsonify(fc)


@bp.get("/api/live-signals.geojson")
def live_signals_geojson():
    fc = data_access.active_official_signal_features()
    if fc is None:
        abort(404)
    return jsonify(fc)


@bp.get("/partials/live-signals")
def live_signals_partial():
    county_slug, county = _county_arg()
    return render_template(
        "partials/live-signals.html",
        signals=data_access.active_official_signals(county_slug),
        county=county,
    )


@bp.get("/partials/metadata/<layer_id>")
def metadata_partial(layer_id: str):
    """Source card shown when a layer or zone is selected."""
    for entry in data_access.available_layers():
        if entry["id"] == layer_id:
            return render_template("partials/metadata.html", layer=entry)
    abort(404)


@bp.get("/partials/events")
def events_partial():
    year = request.args.get("year") or None
    county_slug, county = _county_arg()
    return render_template(
        "partials/events.html",
        events=data_access.flood_events(year, county_slug),
        years=data_access.flood_event_years(county_slug),
        selected_year=year,
        county=county,
    )


@bp.get("/partials/rainfall")
def rainfall_partial():
    county_slug, _ = _county_arg()
    return render_template("partials/rainfall.html", days=data_access.rainfall_records(county_slug))


@bp.get("/partials/reports")
def reports_partial():
    county_slug, county = _county_arg()
    return render_template(
        "partials/reports.html",
        reports=data_access.flood_reports(county_slug),
        county=county,
    )
