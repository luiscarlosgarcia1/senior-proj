#!/usr/bin/env python3
"""Turn the ingested NOAA records into the app database's event tables.

Reads the schema-validated NDJSON under `data/<county>-county/records/` for all
four counties and fills three tables (see `app_db.py`):

  flood_events      documented flood events, all four counties merged; events
                    without a usable coordinate are kept with null lon/lat so
                    the sidebar list can still show them
  flood_reports     the local-news / local-government reports tied to those
                    events -- currently Hidalgo only; the other three counties
                    have no hand-curated reports yet
  rainfall_records  the wettest gauge-days on record, 2000-2025, across every
                    county's stations

Fast, and needs only shapely (a core dependency) — no pipeline dependency group.

Run:  uv run python pipeline/build_events.py
Safe to re-run (replaces only its own three tables).
"""

from __future__ import annotations

from pathlib import Path

from app_db import open_app_db, replace_table
from jsonio import read_ndjson
from paths import APP_DB, DATA_DIR, county_boundary, ghcn_daily_file, storm_events_file
from shapely.geometry import Point, shape

from rgv_flood.counties import SHORT_NAMES as COUNTY_NAMES

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


def build_events() -> list[dict]:
    """`flood_events` rows, newest first."""
    events = []
    for slug, name in COUNTY_NAMES.items():
        boundary = shape(county_boundary(slug, DATA_DIR))
        for r in _records(slug, "flood_event"):
            geometry = r.get("geometry")
            lon = lat = geometry_note = None
            if geometry and geometry.get("type") == "Point":
                lon, lat = geometry["coordinates"][:2]
                if not _near_county(lon, lat, boundary):
                    lon = lat = None
                    geometry_note = (
                        f"The source coordinate falls outside {name} County and looks "
                        "like a data-entry error, so this event is listed but not mapped."
                    )
            events.append({
                "id": r["record_id"],
                "county": slug,
                "date": r["event_start"],
                "date_end": r.get("event_end"),
                "type": _event_type(r.get("summary", "")),
                "location": r.get("location_text", ""),
                "precision": r.get("location_precision"),
                "summary": r.get("summary", ""),
                "source_url": (r.get("source_reference") or {}).get("value"),
                "geometry_note": geometry_note,
                "lon": lon,
                "lat": lat,
            })
    events.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return events


def build_reports() -> list[dict]:
    """`flood_reports` rows, oldest first."""
    reports = []
    for slug in COUNTY_NAMES:
        for r in _records(slug, "public_report"):
            reports.append({
                "county": slug,
                "headline": _first_sentence(r.get("summary", "")),
                "detail": r.get("summary", ""),
                "location": r.get("location_text", ""),
                "published_at": r.get("event_start"),
                "publisher": r.get("source_publisher", ""),
                "channel": r.get("source_channel", ""),
                "source_url": (r.get("source_reference") or {}).get("value"),
                "duplicate_group": r.get("duplicate_group_id"),
            })
    reports.sort(key=lambda report: report["published_at"] or "")
    return reports


def build_rainfall() -> tuple[list[dict], int]:
    """The `rainfall_records` rows (the wettest RAINFALL_TOP_N gauge-days) and
    how many days with measurable rain they were picked from."""
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
                "county": slug,
                "date": attrs["date"],
                "mm": round(mm, 1),
                "inches": round(mm / 25.4, 1),
                "station": attrs["station_name"],
            })
    days.sort(key=lambda d: d["mm"], reverse=True)
    return days[:RAINFALL_TOP_N], len(days)


def main(database: Path = APP_DB) -> None:
    events, reports = build_events(), build_reports()
    wettest, rain_days = build_rainfall()
    with open_app_db(database) as connection:
        replace_table(connection, "flood_events", events)
        replace_table(connection, "flood_reports", reports)
        replace_table(connection, "rainfall_records", wettest)

    mapped = sum(1 for e in events if e["lat"] is not None)
    dropped = sum(1 for e in events if e["geometry_note"])
    note = f", {dropped} bad coordinate(s) dropped" if dropped else ""
    print(f"flood_events: {len(events)} events across {len(COUNTY_NAMES)} counties ({mapped} mapped{note})")
    curated = sorted({r["county"] for r in reports})
    print(f"flood_reports: {len(reports)} reports (curated so far for: {', '.join(curated) or 'none'})")
    print(f"rainfall_records: top {len(wettest)} of {rain_days} days with measurable rain, all counties")
    print("written to", database)


if __name__ == "__main__":
    main()
