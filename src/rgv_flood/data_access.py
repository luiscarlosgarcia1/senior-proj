"""Read-only access to pipeline outputs.

The app serves what the offline pipeline produced. It does not fetch from FEMA,
TWDB, Census, or news sites at request time.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import current_app


def _map_data_dir() -> Path:
    return Path(current_app.config["MAP_DATA_DIR"])


def _read_json(config_key: str) -> dict | None:
    path = Path(current_app.config[config_key])
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def available_layers() -> list[dict]:
    """Layer manifest written by the pipeline: id, title, source, vintage, file."""
    manifest = _map_data_dir() / "layers.json"
    if not manifest.exists():
        return []
    return json.loads(manifest.read_text(encoding="utf-8")).get("layers", [])


def layer_path(layer_id: str) -> Path | None:
    """The built GeoJSON file for a layer, if it is listed and exists."""
    for layer in available_layers():
        if layer["id"] == layer_id:
            path = _map_data_dir() / layer["file"]
            return path if path.exists() else None
    return None


def flood_events_fc() -> dict | None:
    """The documented-flood-event points as a GeoJSON FeatureCollection."""
    return _read_json("FLOOD_EVENTS_FILE")


def flood_events(year: str | None = None, county_slug: str | None = None) -> list[dict]:
    """Event rows (newest first), optionally filtered to one year and/or county.

    Each row is the feature's properties plus ``lat`` / ``lon`` when the event
    has a point, so the sidebar list can fly the map to it.
    """
    fc = flood_events_fc()
    if not fc:
        return []
    rows = []
    for feature in fc["features"]:
        row = dict(feature["properties"])
        geom = feature.get("geometry")
        if geom and geom.get("type") == "Point":
            row["lon"], row["lat"] = geom["coordinates"][:2]
        rows.append(row)
    if year:
        rows = [r for r in rows if r.get("date", "").startswith(year)]
    if county_slug:
        rows = [r for r in rows if r.get("county") == county_slug]
    return rows


def flood_event_years(county_slug: str | None = None) -> list[str]:
    return sorted(
        {e["date"][:4] for e in flood_events(county_slug=county_slug) if e.get("date")}, reverse=True
    )


def flood_reports(county_slug: str | None = None) -> list[dict]:
    """Local-news and local-government reports tied to documented flood events.

    Historical only — never live closure data. Each report carries its source
    URL and publication date.
    """
    data = _read_json("FLOOD_REPORTS_FILE")
    reports = data.get("reports", []) if data else []
    if county_slug:
        reports = [r for r in reports if r.get("county") == county_slug]
    return reports


def rainfall_records(county_slug: str | None = None) -> list[dict]:
    """The wettest single gauge-days on record (date, mm, inches, station)."""
    data = _read_json("RAINFALL_FILE")
    days = data.get("days", []) if data else []
    if county_slug:
        days = [d for d in days if d.get("county") == county_slug]
    return days


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
    database = Path(current_app.config["LIVE_SIGNALS_DATABASE"])
    if not database.exists():
        return None
    query = (
        f"select {', '.join(columns)} from live_signals "
        "where lifecycle_state = 'active' and provenance = 'official'"
        + (" and is_mappable = 1" if only_mappable else "")
        + (f" order by {order_by}" if order_by else "")
    )
    # closing(): sqlite3's own context manager commits but never closes the file.
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query)]


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
