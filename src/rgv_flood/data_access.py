"""Read-only access to pipeline outputs.

The app serves what the offline pipeline produced. It does not fetch from FEMA,
TWDB, Census, or news sites at request time.
"""

from __future__ import annotations

import json
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


def layer_geojson(layer_id: str) -> dict | None:
    for layer in available_layers():
        if layer["id"] == layer_id:
            path = _map_data_dir() / layer["file"]
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
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
