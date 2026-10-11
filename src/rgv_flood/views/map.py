"""Routes for the single-page map and its HTMX partials."""

from __future__ import annotations

from flask import Blueprint, Response, abort, jsonify, render_template, request

from rgv_flood import data_access
from rgv_flood.counties import COUNTIES, RGV_BBOX, is_county
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
        bbox=RGV_BBOX,
        layers=data_access.available_layers(),
        relative_classes=RELATIVE_CLASSES,
        event_count=data_access.flood_event_count(),
    )


@bp.get("/api/layers/<layer_id>.geojson")
def layer(layer_id: str):
    """The layer's GeoJSON as the pipeline built it. Layers run to several MB, so
    a browser that already holds the current version is told so (304) without
    the geometry being read at all."""
    etag = data_access.layer_etag(layer_id)
    if etag is None:
        abort(404)
    if etag in request.if_none_match:
        response = Response(status=304)
    else:
        response = Response(data_access.layer_geojson(layer_id), mimetype="application/json")
    response.set_etag(etag)
    return response


@bp.get("/api/flood-events.geojson")
def flood_events_geojson():
    collection = data_access.flood_events_geojson()
    if collection is None:
        abort(404)
    return jsonify(collection)


@bp.get("/api/live-signals.geojson")
def live_signals_geojson():
    collection = data_access.active_official_signal_features()
    if collection is None:
        abort(404)
    return jsonify(collection)


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
    entry = data_access.layer(layer_id)
    if entry is None:
        abort(404)
    return render_template("partials/metadata.html", layer=entry)


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
