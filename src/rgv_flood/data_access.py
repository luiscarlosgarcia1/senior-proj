"""Read-only access to pipeline outputs.

The app serves what the offline pipeline produced: the app database (map
layers, flood events, reports, rainfall; see `pipeline/app_db.py` for its
tables) and the live-signals database. It does not fetch from FEMA, TWDB,
Census, or news sites at request time.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import current_app

LAYER_COLUMNS = (
    "id, title, description, source, vintage, hazard_type, coverage, limitation, source_url, "
    "visualizations_json, feature_count"
)
EVENT_COLUMNS = "id, county, date, date_end, type, location, precision, summary, source_url, geometry_note, lon, lat"


def _rows(database_key: str, query: str, parameters: tuple = ()) -> list[dict] | None:
    """Rows of a query as dicts, or None when that database hasn't been built yet."""
    database = Path(current_app.config[database_key])
    if not database.exists():
        return None
    # closing(): sqlite3's own context manager commits but never closes the file.
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, parameters)]


def _app_rows(query: str, parameters: tuple = ()) -> list[dict]:
    return _rows("APP_DATABASE", query, parameters) or []


def _where(equals: dict[str, str | None]) -> tuple[str, tuple]:
    """A WHERE clause (and its parameters) for every column expression given a value."""
    wanted = {expression: value for expression, value in equals.items() if value}
    if not wanted:
        return "", ()
    return " where " + " and ".join(f"{expression} = ?" for expression in wanted), tuple(wanted.values())


# ---- map layers ----


def _layer(row: dict) -> dict:
    row["visualizations"] = json.loads(row.pop("visualizations_json"))
    return row


def available_layers() -> list[dict]:
    """Every layer's descriptive metadata (not its geometry), in sidebar order."""
    return [_layer(row) for row in _app_rows(f"select {LAYER_COLUMNS} from layers order by position")]


def layer(layer_id: str) -> dict | None:
    """One layer's descriptive metadata."""
    rows = _app_rows(f"select {LAYER_COLUMNS} from layers where id = ?", (layer_id,))
    return _layer(rows[0]) if rows else None


def layer_etag(layer_id: str) -> str | None:
    """A token that changes whenever the layer's GeoJSON does (None for an unknown layer)."""
    rows = _app_rows("select etag from layers where id = ?", (layer_id,))
    return rows[0]["etag"] if rows else None


def layer_geojson(layer_id: str) -> bytes | None:
    """The layer's FeatureCollection, exactly as the pipeline built it."""
    rows = _app_rows("select geojson from layers where id = ?", (layer_id,))
    return rows[0]["geojson"] if rows else None


# ---- flood events, reports, rainfall ----


def _events(where: str = "", parameters: tuple = ()) -> list[dict] | None:
    query = f"select {EVENT_COLUMNS} from flood_events{where} order by date desc, id desc"
    return _rows("APP_DATABASE", query, parameters)


def flood_events(year: str | None = None, county_slug: str | None = None) -> list[dict]:
    """Event rows (newest first), optionally filtered to one year and/or county.

    ``lat`` / ``lon`` are None when the event has no point to fly the map to.
    """
    return _events(*_where({"substr(date, 1, 4)": year, "county": county_slug})) or []


def flood_event_count() -> int:
    rows = _app_rows("select count(*) as total from flood_events")
    return rows[0]["total"] if rows else 0


def flood_event_years(county_slug: str | None = None) -> list[str]:
    where, parameters = _where({"county": county_slug})
    rows = _app_rows(f"select distinct substr(date, 1, 4) as year from flood_events{where} order by year desc", parameters)
    return [row["year"] for row in rows]


def flood_events_geojson() -> dict | None:
    """Every event as a GeoJSON feature for the map (None before the first build)."""
    events = _events()
    if events is None:
        return None
    features = []
    for event in events:
        lon, lat = event.pop("lon"), event.pop("lat")
        geometry = {"type": "Point", "coordinates": [lon, lat]} if lat is not None else None
        features.append({"type": "Feature", "geometry": geometry, "properties": event})
    return {"type": "FeatureCollection", "features": features}


def flood_reports(county_slug: str | None = None) -> list[dict]:
    """Local-news and local-government reports tied to documented flood events.

    Historical only — never live closure data. Each report carries its source
    URL and publication date.
    """
    where, parameters = _where({"county": county_slug})
    return _app_rows(f"select * from flood_reports{where} order by report_id", parameters)


def rainfall_records(county_slug: str | None = None) -> list[dict]:
    """The wettest single gauge-days on record (date, mm, inches, station)."""
    where, parameters = _where({"county": county_slug})
    return _app_rows(f"select * from rainfall_records{where} order by rank", parameters)


# ---- live signals ----

# Columns of the live_signals table that each consumer needs.
MAP_SIGNAL_COLUMNS = (
    "source", "native_id", "source_url", "source_publisher", "source_channel", "summary",
    "source_attributes_json", "county_slugs_json", "inclusion_basis", "source_geometry_json",
    "published_at", "effective_at", "source_updated_at", "expires_at", "first_seen_at",
    "last_seen_at", "retrieved_at",
)
SIDEBAR_SIGNAL_COLUMNS = (
    "source", "native_id", "source_url", "source_publisher", "source_channel", "summary",
    "county_slugs_json", "source_geometry_json", "geometry_absence_reason", "is_mappable",
    "published_at", "effective_at", "source_updated_at", "expires_at", "last_seen_at", "retrieved_at",
)


def _active_official_signals(
    columns: tuple[str, ...], *, only_mappable: bool, order_by: str = ""
) -> list[dict] | None:
    """Active, official rows of the live-signals database (None if it doesn't exist yet)."""
    return _rows(
        "LIVE_SIGNALS_DATABASE",
        f"select {', '.join(columns)} from live_signals "
        "where lifecycle_state = 'active' and provenance = 'official'"
        + (" and is_mappable = 1" if only_mappable else "")
        + (f" order by {order_by}" if order_by else ""),
    )


def active_official_signal_features() -> dict | None:
    """Active official signals that carry source geometry, as GeoJSON for the map."""
    rows = _active_official_signals(MAP_SIGNAL_COLUMNS, only_mappable=True)
    if rows is None:
        return None
    features = []
    for row in rows:
        geometry = json.loads(row.pop("source_geometry_json"))
        row["source_attributes"] = json.loads(row.pop("source_attributes_json"))
        row["county_slugs"] = json.loads(row.pop("county_slugs_json"))
        features.append({"type": "Feature", "geometry": geometry, "properties": row})
    return {"type": "FeatureCollection", "features": features}


def active_official_signals(county_slug: str | None = None) -> list[dict]:
    """Active official signals for the sidebar, including notices.

    Signals without source geometry stay in this list so the UI can link to
    them without inventing a map location.
    """
    rows = _active_official_signals(
        SIDEBAR_SIGNAL_COLUMNS, only_mappable=False, order_by="retrieved_at desc, source_publisher, summary"
    )
    signals = []
    for row in rows or []:
        row["county_slugs"] = json.loads(row.pop("county_slugs_json"))
        row["is_mappable"] = bool(row["is_mappable"])
        if county_slug is None or county_slug in row["county_slugs"]:
            signals.append(row)
    return signals
