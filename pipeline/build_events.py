#!/usr/bin/env python3
"""Turn the ingested NOAA records into app-ready overlays.

Reads the schema-validated NDJSON under `data/<county>-county/records/` for all
four counties and writes, into `src/rgv_flood/static/data/`:

  flood-events.geojson   documented flood events as map points, all four
                         counties merged (each feature carries its own
                         `county`); events without a coordinate are kept with
                         null geometry so the sidebar list can still show them
  flood-reports.json     the local-news / local-government reports tied to
                         those events -- currently Hidalgo only; the other
                         three counties have no hand-curated reports yet
  rainfall-records.json  the wettest gauge-days on record, 2000-2025, across
                         every county's stations

Pure standard library and fast — no need for the pipeline dependency group.

Run:  uv run python pipeline/build_events.py
Safe to re-run (overwrites only its own three outputs).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
OUT_DIR = REPO_ROOT / "src" / "rgv_flood" / "static" / "data"

COUNTIES = {"cameron": "Cameron", "hidalgo": "Hidalgo", "starr": "Starr", "willacy": "Willacy"}

RAINFALL_TOP_N = 15

# A handful of NOAA Storm Events rows carry a BEGIN_LAT/LON that is plainly a
# data-entry error -- e.g. a Hidalgo "MC ALLEN" event pinned near Harlingen (in
# Cameron County), or a Cameron "BROWNSVILLE" event pinned just south of the
# river, in Mexico. A bounding box is too coarse to catch the second kind of
# error along a winding river border like Cameron's or Starr's, so this checks
# the point against the county's real boundary polygon (with a small distance
# tolerance for ordinary reporting imprecision, not a lon/lat buffer). Points
# that fail are not plotted; the event is kept in the list under its stated
# location_text rather than shown at a wrong coordinate -- possibly in the
# wrong country.
BOUNDARY_TOLERANCE_DEG = 0.01  # ~1.1 km


def _county_ring(slug: str) -> list[tuple[float, float]]:
    """The exterior ring of one county's TIGER boundary. These are simple
    single-ring Polygons (verified: no holes, no MultiPolygon), so this does
    not need to handle either."""
    boundary = json.loads(
        (DATA_DIR / f"{slug}-county" / "flood-hazard-layers" / "boundary.geojson").read_text(
            encoding="utf-8"
        )
    )
    geometry = boundary["features"][0]["geometry"]
    if geometry["type"] != "Polygon":
        raise ValueError(f"{slug}: expected a Polygon boundary, got {geometry['type']}")
    return [(x, y) for x, y in geometry["coordinates"][0]]


def _point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Standard ray-casting point-in-polygon test."""
    inside = False
    x1, y1 = ring[0]
    for x2, y2 in ring[1:]:
        if (y1 > lat) != (y2 > lat):
            x_at_lat = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_at_lat:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def _distance_to_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> float:
    """Shortest distance (degrees) from a point to any edge of the ring."""

    def segment_distance(ax: float, ay: float, bx: float, by: float) -> float:
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(lon - ax, lat - ay)
        t = max(0.0, min(1.0, ((lon - ax) * dx + (lat - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(lon - (ax + t * dx), lat - (ay + t * dy))

    return min(
        segment_distance(ring[i][0], ring[i][1], ring[i + 1][0], ring[i + 1][1])
        for i in range(len(ring) - 1)
    )


def _near_county(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    return _point_in_ring(lon, lat, ring) or _distance_to_ring(lon, lat, ring) <= BOUNDARY_TOLERANCE_DEG


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
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


def build_events() -> int:
    features = []
    dropped_coords = 0
    for slug, name in COUNTIES.items():
        ring = _county_ring(slug)
        path = DATA_DIR / f"{slug}-county" / "records" / "events-and-public-reports" / "noaa-storm-events.ndjson"
        for r in _load(path):
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
                "county": slug,
            }
            if geometry and geometry.get("type") == "Point":
                lon, lat = geometry["coordinates"][:2]
                if not _near_county(lon, lat, ring):
                    geometry = None
                    props["geometry_note"] = (
                        f"The source coordinate falls outside {name} County and looks "
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
    print(f"flood-events.geojson: {len(features)} events across {len(COUNTIES)} counties ({mapped} mapped{note})")
    return len(features)


def build_reports() -> int:
    reports = []
    for slug in COUNTIES:
        path = DATA_DIR / f"{slug}-county" / "records" / "events-and-public-reports" / "noaa-storm-events.ndjson"
        for r in _load(path):
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
                "county": slug,
            })
    reports.sort(key=lambda x: x["published_at"] or "")
    (OUT_DIR / "flood-reports.json").write_text(
        json.dumps({"generated_by": "pipeline/build_events.py", "reports": reports}, indent=2) + "\n",
        encoding="utf-8",
    )
    by_county = sorted({r["county"] for r in reports})
    print(f"flood-reports.json: {len(reports)} reports (curated so far for: {', '.join(by_county) or 'none'})")
    return len(reports)


def build_rainfall() -> int:
    days = []
    for slug in COUNTIES:
        path = DATA_DIR / f"{slug}-county" / "records" / "layers-and-weather" / "noaa-ghcn-daily-2000-2025.ndjson"
        for w in _load(path):
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
                "county": slug,
            })
    days.sort(key=lambda d: d["mm"], reverse=True)
    top = days[:RAINFALL_TOP_N]
    (OUT_DIR / "rainfall-records.json").write_text(
        json.dumps({"generated_by": "pipeline/build_events.py", "days": top}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"rainfall-records.json: top {len(top)} of {len(days)} days with measurable rain, all counties")
    return len(top)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_events()
    build_reports()
    build_rainfall()


if __name__ == "__main__":
    main()
