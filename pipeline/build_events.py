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

Fast, and needs only shapely (a core dependency) — no pipeline dependency group.

Run:  uv run python pipeline/build_events.py
Safe to re-run (overwrites only its own three outputs).
"""

from __future__ import annotations

import json

from jsonio import feature_collection, read_ndjson, write_json
from paths import DATA_DIR, OUT_DIR, county_boundary, ghcn_daily_file, storm_events_file
from shapely.geometry import Point, shape

from rgv_flood.counties import SHORT_NAMES as COUNTY_NAMES

GENERATED_BY = "pipeline/build_events.py"
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


def _near_county(lon: float, lat: float, boundary) -> bool:
    """Inside the county, or within the reporting-error tolerance of its edge."""
    return boundary.distance(Point(lon, lat)) <= BOUNDARY_TOLERANCE_DEG  # 0 when inside


def _records(slug: str, record_kind: str) -> list[dict]:
    """One kind of record from a county's storm-events file (which also holds its public reports)."""
    return [r for r in read_ndjson(storm_events_file(slug, DATA_DIR)) if r.get("record_kind") == record_kind]


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
    for slug, name in COUNTY_NAMES.items():
        boundary = shape(county_boundary(slug, DATA_DIR))
        for r in _records(slug, "flood_event"):
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
                if not _near_county(lon, lat, boundary):
                    geometry = None
                    props["geometry_note"] = (
                        f"The source coordinate falls outside {name} County and looks "
                        "like a data-entry error, so this event is listed but not mapped."
                    )
                    dropped_coords += 1
            features.append({"type": "Feature", "geometry": geometry, "properties": props})
    features.sort(key=lambda f: (f["properties"]["date"], f["properties"]["id"]), reverse=True)
    (OUT_DIR / "flood-events.geojson").write_text(json.dumps(feature_collection(features)), encoding="utf-8")
    mapped = sum(1 for f in features if f["geometry"])
    note = f", {dropped_coords} bad coordinate(s) dropped" if dropped_coords else ""
    print(f"flood-events.geojson: {len(features)} events across {len(COUNTY_NAMES)} counties ({mapped} mapped{note})")
    return len(features)


def build_reports() -> int:
    reports = []
    for slug in COUNTY_NAMES:
        for r in _records(slug, "public_report"):
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
    write_json(OUT_DIR / "flood-reports.json", {"generated_by": GENERATED_BY, "reports": reports})
    by_county = sorted({r["county"] for r in reports})
    print(f"flood-reports.json: {len(reports)} reports (curated so far for: {', '.join(by_county) or 'none'})")
    return len(reports)


def build_rainfall() -> int:
    days = []
    for slug in COUNTY_NAMES:
        for w in read_ndjson(ghcn_daily_file(slug, DATA_DIR)):
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
    write_json(OUT_DIR / "rainfall-records.json", {"generated_by": GENERATED_BY, "days": top})
    print(f"rainfall-records.json: top {len(top)} of {len(days)} days with measurable rain, all counties")
    return len(top)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_events()
    build_reports()
    build_rainfall()


if __name__ == "__main__":
    main()
