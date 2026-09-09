#!/usr/bin/env python3
"""Turn the ingested NOAA records into app-ready overlays.

Reads the schema-validated NDJSON under `data/hidalgo-county/records/` (collected
by Luis) and writes, into `src/rgv_flood/static/data/`:

  flood-events.geojson   documented flood events as map points; events without a
                         coordinate are kept with null geometry so the sidebar
                         list can still show them
  flood-reports.json     the local-news / local-government reports tied to those
                         events
  rainfall-records.json  the wettest gauge-days on record, 2000-2025

Pure standard library and fast — no need for the pipeline dependency group.

Run:  uv run python pipeline/build_events.py
Safe to re-run (overwrites only its own three outputs).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORDS = REPO_ROOT / "data" / "hidalgo-county" / "records"
OUT_DIR = REPO_ROOT / "src" / "rgv_flood" / "static" / "data"

EVENTS_NDJSON = RECORDS / "events-and-public-reports" / "noaa-storm-events.ndjson"
WEATHER_NDJSON = RECORDS / "layers-and-weather" / "noaa-ghcn-daily-2000-2025.ndjson"

RAINFALL_TOP_N = 15

# Hidalgo County's TIGER boundary bbox is roughly lon -98.586..-97.862,
# lat 26.036..26.783. A handful of NOAA Storm Events rows carry a BEGIN_LAT/LON
# that is plainly a data-entry error — e.g. a "MC ALLEN" event pinned near
# Harlingen. Points outside this (slightly buffered) box are not plotted; the
# event is kept in the list under its stated location_text rather than shown at
# a wrong coordinate.
COUNTY_BOX = (-98.63, 25.99, -97.82, 26.83)  # lon_min, lat_min, lon_max, lat_max


def _in_county_box(lon: float, lat: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = COUNTY_BOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _event_type(summary: str) -> str:
    s = summary.lower()
    for phrase, label in (
        ("flash flood", "Flash flood"),
        ("heavy rain", "Heavy rain"),
        ("coastal flood", "Coastal flood"),
        ("lakeshore flood", "Lakeshore flood"),
        ("debris flow", "Debris flow"),
    ):
        if phrase in s:
            return label
    return "Flood"


def _first_sentence(text: str) -> str:
    for mark in (". ", "? ", "! "):
        i = text.find(mark)
        if i != -1:
            return text[: i + 1].strip()
    return text.strip()


def build_events(records: list[dict]) -> int:
    features = []
    dropped_coords = 0
    for r in records:
        if r.get("record_kind") != "flood_event":
            continue
        ref = r.get("source_reference") or {}
        geometry = r.get("geometry")
        props = {
            "id": r["record_id"],
            "date": r["event_start"],
            "date_end": r.get("event_end"),
            "type": _event_type(r.get("summary", "")),
            "location": r.get("location_text", ""),
            "precision": r.get("location_precision"),
            "summary": r.get("summary", ""),
            "source_url": ref.get("value"),
            "county": "hidalgo",
        }
        if geometry and geometry.get("type") == "Point":
            lon, lat = geometry["coordinates"][:2]
            if not _in_county_box(lon, lat):
                geometry = None
                props["geometry_note"] = (
                    "The source coordinate falls outside Hidalgo County and looks "
                    "like a data-entry error, so this event is listed but not mapped."
                )
                dropped_coords += 1
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    features.sort(key=lambda f: (f["properties"]["date"], f["properties"]["id"]), reverse=True)
    (OUT_DIR / "flood-events.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    mapped = sum(1 for f in features if f["geometry"])
    note = f", {dropped_coords} bad coordinate(s) dropped" if dropped_coords else ""
    print(f"flood-events.geojson: {len(features)} events ({mapped} mapped{note})")
    return len(features)


def build_reports(records: list[dict]) -> int:
    reports = []
    for r in records:
        if r.get("record_kind") != "public_report":
            continue
        ref = r.get("source_reference") or {}
        reports.append({
            "headline": _first_sentence(r.get("summary", "")),
            "detail": r.get("summary", ""),
            "location": r.get("location_text", ""),
            "published_at": r.get("event_start"),
            "publisher": r.get("source_publisher", ""),
            "channel": r.get("source_channel", ""),
            "source_url": ref.get("value"),
            "group": r.get("duplicate_group_id"),
            "county": "hidalgo",
        })
    reports.sort(key=lambda x: x["published_at"] or "")
    (OUT_DIR / "flood-reports.json").write_text(
        json.dumps({"generated_by": "pipeline/build_events.py", "reports": reports}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"flood-reports.json: {len(reports)} reports")
    return len(reports)


def build_rainfall(weather: list[dict]) -> int:
    days = []
    for w in weather:
        attrs = w["original_attributes"]
        prcp = attrs["observations"].get("PRCP")
        if not prcp or prcp.get("value") is None:
            continue
        mm = prcp["value"] / 10.0
        if mm <= 0:
            continue
        days.append({
            "date": attrs["date"],
            "mm": round(mm, 1),
            "inches": round(mm / 25.4, 1),
            "station": attrs["station_name"],
        })
    days.sort(key=lambda d: d["mm"], reverse=True)
    top = days[:RAINFALL_TOP_N]
    (OUT_DIR / "rainfall-records.json").write_text(
        json.dumps({"generated_by": "pipeline/build_events.py", "days": top}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"rainfall-records.json: top {len(top)} of {len(days)} days with measurable rain")
    return len(top)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = _load(EVENTS_NDJSON)
    build_events(records)
    build_reports(records)
    build_rainfall(_load(WEATHER_NDJSON))


if __name__ == "__main__":
    main()
