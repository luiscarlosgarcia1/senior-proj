"""Routes for the single-page map and its HTMX partials."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)

from rgv_flood import data_access
from rgv_flood.counties import COUNTIES, RGV_BBOX, is_county
from rgv_flood.db import Database
from rgv_flood.severity import RELATIVE_CLASSES

bp = Blueprint("map", __name__)


def _db() -> Database:
    return Database(current_app.config["DATABASE"])


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
        layers=data_access.available_layers(_db()),
        relative_classes=RELATIVE_CLASSES,
        event_count=data_access.flood_event_count(_db()),
    )


@bp.get("/api/layers/<layer_id>.geojson")
def layer(layer_id: str):
    """The layer's GeoJSON as the pipeline built it.

    Layers run to several MB, so they are stored gzipped and sent that way to
    any browser that accepts it (all of them), and a browser that already holds
    the current version is told so (304) without the geometry being read at all.
    """
    etag = data_access.layer_etag(_db(), layer_id)
    if etag is None:
        abort(404)
    if etag in request.if_none_match:
        response = Response(status=304)
    else:
        body = data_access.layer_geojson_gzip(_db(), layer_id)
        if "gzip" in request.accept_encodings:
            response = Response(body, mimetype="application/json", headers={"Content-Encoding": "gzip"})
        else:
            response = Response(gzip.decompress(body), mimetype="application/json")
    response.set_etag(etag)
    response.vary.add("Accept-Encoding")
    return response


@bp.get("/api/flood-events.geojson")
def flood_events_geojson():
    collection = data_access.flood_events_geojson(_db())
    if collection is None:
        abort(404)
    return jsonify(collection)


@bp.get("/api/live-signals.geojson")
def live_signals_geojson():
    collection = data_access.active_official_signal_features(_db())
    if collection is None:
        abort(404)
    return jsonify(collection)


@bp.get("/partials/live-signals")
def live_signals_partial():
    county_slug, county = _county_arg()
    return render_template(
        "partials/live-signals.html",
        signals=data_access.active_official_signals(_db(), county_slug),
        county=county,
    )


@bp.get("/partials/metadata/<layer_id>")
def metadata_partial(layer_id: str):
    """Source card shown when a layer or zone is selected."""
    entry = data_access.layer(_db(), layer_id)
    if entry is None:
        abort(404)
    return render_template("partials/metadata.html", layer=entry)


@bp.get("/partials/events")
def events_partial():
    year = request.args.get("year") or None
    county_slug, county = _county_arg()
    return render_template(
        "partials/events.html",
        events=data_access.flood_events(_db(), year, county_slug),
        years=data_access.flood_event_years(_db(), county_slug),
        selected_year=year,
        county=county,
    )


@bp.get("/partials/events/<event_id>/context")
def event_context_partial(event_id: str):
    """What else the database holds about an event's days: rain at nearby
    gauges and local reports. Shown inside the event's map popup."""
    event = data_access.flood_event(_db(), event_id)
    if event is None:
        abort(404)
    return render_template(
        "partials/event-context.html",
        county=COUNTIES[event["county"]],
        rainfall=data_access.rainfall_near_event(_db(), event),
        reports=data_access.reports_near_event(_db(), event),
    )


@bp.get("/partials/rainfall")
def rainfall_partial():
    county_slug, county = _county_arg()
    return render_template(
        "partials/rainfall.html", days=data_access.rainfall_records(_db(), county_slug), county=county
    )


@bp.get("/analysis")
def analysis():
    """Flood-insurance claims beside rainfall, year by year. The data for all
    four counties and each one is embedded, so switching county needs no request."""
    last_year = datetime.now(UTC).year - 1  # the current year isn't over
    histories = {"all": data_access.history_by_year(_db(), None, last_year)}
    histories |= {slug: data_access.history_by_year(_db(), slug, last_year) for slug in COUNTIES}
    return render_template(
        "analysis.html",
        counties=COUNTIES,
        histories=histories,
        first_year=data_access.HISTORY_FIRST_YEAR,
        last_year=last_year,
        complete_days=data_access.COMPLETE_GAUGE_DAYS,
    )


@bp.get("/partials/sources")
def sources_partial():
    return render_template("partials/sources.html", sources=data_access.data_sources(_db()))


@bp.get("/partials/reports")
def reports_partial():
    county_slug, county = _county_arg()
    return render_template(
        "partials/reports.html",
        reports=data_access.flood_reports(_db(), county_slug),
        county=county,
    )
