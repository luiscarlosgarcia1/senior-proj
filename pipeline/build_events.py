#!/usr/bin/env python3
"""Load flood events, local reports, historic news and weather into the central database.

Pulls NOAA's Storm Events and GHCN-Daily files (downloading only what the cache
lacks), reads them into memory with `noaa.py`, adds the hand-curated reports
from `data/seed/`, and fills four tables (see `database.py`):

  flood_events          every flood-type NOAA event for the four counties; an
                        event with no usable coordinate keeps null lon/lat so
                        the sidebar list can still show it
  flood_reports         local-news / local-government reports tied to those
                        events -- currently Hidalgo only; the other three
                        counties have no hand-curated reports yet
  weather_stations      the GHCN-Daily stations used for each county
  weather_observations  their daily readings, 2000-2025

Needs only shapely (a core dependency) — no pipeline dependency group.

Run:  uv run python pipeline/build_events.py
Safe to re-run (replaces only its own tables).
"""

from __future__ import annotations

from pathlib import Path

import noaa
from database import open_database, record_sources, replace_table
from historic_news_sources import records as historic_news_records
from jsonio import read_ndjson
from paths import DATABASE, SEED_DIR, county_boundary, seed_file
from shapely.geometry import Point, shape

from rgv_flood.counties import SHORT_NAMES

# A handful of NOAA Storm Events rows carry a BEGIN_LAT/LON that is plainly a
# data-entry error -- e.g. a Hidalgo "MC ALLEN" event pinned near Harlingen (in
# Cameron County), or a Cameron "BROWNSVILLE" event pinned just south of the
# river, in Mexico. A bounding box is too coarse to catch the second kind of
# error along a winding river border like Cameron's or Starr's, so this checks
# the point against the county's real boundary polygon (with a small distance
# tolerance for ordinary reporting imprecision, not a lon/lat buffer). Points
# that fail are not plotted; the event is kept in the list under its stated
# location rather than shown at a wrong coordinate -- possibly in the wrong
# country.
BOUNDARY_TOLERANCE_DEG = 0.01  # ~1.1 km


def _near_county(lon: float, lat: float, boundary) -> bool:
    """Inside the county, or within the reporting-error tolerance of its edge."""
    return boundary.distance(Point(lon, lat)) <= BOUNDARY_TOLERANCE_DEG  # 0 when inside


def _inside_county(lon: float, lat: float, boundary) -> bool:
    """Whether a historic-news point has evidence for an in-county location."""
    return boundary.covers(Point(lon, lat))


def _plot(event: dict, boundary) -> dict:
    """The event with the point the map should show for it (lon/lat), which is
    NOAA's own coordinate unless that falls outside the event's county."""
    lon, lat, note = event["source_lon"], event["source_lat"], None
    if lon is not None and not _near_county(lon, lat, boundary):
        lon = lat = None
        note = (
            f"The source coordinate falls outside {SHORT_NAMES[event['county']]} County and looks "
            "like a data-entry error, so this event is listed but not mapped."
        )
    return {**event, "lon": lon, "lat": lat, "geometry_note": note}


def flood_events(counties: list[str], raw_dir: Path, seed_dir: Path) -> list[dict]:
    """`flood_events` rows, newest first."""
    boundaries = {slug: shape(county_boundary(slug, seed_dir)) for slug in counties}
    events = [_plot(event, boundaries[event["county"]]) for event in noaa.storm_events(counties, raw_dir)]
    events.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return events


def _first_sentence(text: str) -> str:
    for mark in (". ", "? ", "! "):
        i = text.find(mark)
        if i != -1:
            return text[: i + 1].strip()
    return text.strip()


def flood_reports(counties: list[str], seed_dir: Path) -> list[dict]:
    """`flood_reports` rows from each county's curated seed file, oldest first."""
    reports = []
    for slug in counties:
        for r in read_ndjson(seed_file(slug, "public-reports.ndjson", seed_dir)):
            reports.append({
                "id": r["record_id"],
                "county": slug,
                "headline": _first_sentence(r.get("summary", "")),
                "detail": r.get("summary", ""),
                "location": r.get("location_text", ""),
                "location_precision": r.get("location_precision"),
                "event_date": r.get("event_start"),
                "event_end": r.get("event_end"),
                "published_at": r.get("published_at"),
                "publisher": r.get("source_publisher", ""),
                "channel": r.get("source_channel", ""),
                "source_url": (r.get("source_reference") or {}).get("value"),
                "original_content": r.get("original_content_reference"),
                "duplicate_group": r.get("duplicate_group_id"),
                "retrieved_at": r.get("retrieved_at"),
            })
    reports.sort(key=lambda report: report["event_date"] or "")
    return reports


def _historic_news_location(record: dict, county: str, boundary) -> dict:
    """Turn one record's location evidence into a point only when it warrants one.

    The seed is the reproducible location authority.  We never call a live
    geocoder here and never substitute a municipal or county centroid for an
    article's uncertain location.
    """
    coordinates = record.get("source_coordinates") or record.get("fixed_place_coordinates")
    precision = "source_coordinate" if record.get("source_coordinates") else record.get("location_precision", "unresolved")
    location_text = record.get("location_text")
    reason = record.get("geometry_absence_reason")
    source_lon = source_lat = lon = lat = None

    if coordinates is not None:
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise ValueError(f"{record['record_id']}: coordinates must be [longitude, latitude]")
        source_lon, source_lat = coordinates
        if not all(isinstance(value, (int, float)) for value in coordinates):
            raise ValueError(f"{record['record_id']}: coordinates must be numeric")
        if _inside_county(source_lon, source_lat, boundary):
            lon, lat = source_lon, source_lat
            precision = "source_coordinate" if record.get("source_coordinates") else "fixed_place"
        else:
            reason = (
                f"The supplied location falls outside {SHORT_NAMES[county]} County, so this historic report is retained "
                "without a map point."
            )
    elif precision not in {"municipality", "county", "regional", "unresolved", "ambiguous"}:
        raise ValueError(f"{record['record_id']}: non-mappable evidence needs a recognized location_precision")

    if lon is None and not reason:
        reason = "The report does not provide a fixed, unambiguous in-county location, so it is retained without a map point."
    return {
        "location_text": location_text, "location_precision": precision, "geometry_reason": reason,
        "source_lon": source_lon, "source_lat": source_lat, "lon": lon, "lat": lat,
    }


def historic_news(counties: list[str], seed_dir: Path) -> list[dict]:
    """Authorized historic-news evidence, including valid non-mappable records."""
    records = []
    for record in historic_news_records(counties, seed_dir):
        slug = record["county"]
        boundary = shape(county_boundary(slug, seed_dir))
        records.append({
            "id": record["record_id"], "county": slug,
            "headline": record["headline"], "summary": record["summary"],
            "published_at": record["published_at"], "publisher": record["source_publisher"],
            "source_url": record["canonical_url"],
            "retrieved_at": record["retrieved_at"],
            **_historic_news_location(record, slug, boundary),
        })
    return sorted(records, key=lambda record: (record["published_at"], record["id"]))


def _reports_source(reports: list[dict]) -> dict:
    return {
        "id": "local-public-reports",
        "publisher": "Local news outlets and local governments",
        "dataset": "Hand-curated public flood reports",
        "url": None,
        "retrieved_at": None,
        "record_count": len(reports),
        "notes": (
            "Curated by hand (data/seed/<county>/public-reports.ndjson) from public-web searches around NOAA "
            "event dates and places; each row keeps its own source URL, source date and retrieval date."
        ),
    }


def _historic_news_source(records: list[dict]) -> dict:
    return {
        "id": "historic-news:the-brownsville",
        "publisher": "The Brownsville",
        "dataset": "Authorized historic-news evidence fixture",
        "url": "https://thebrownsville.org/",
        "retrieved_at": None,
        "record_count": len(records),
        "notes": "Historic attributed reporting only. It is not a live alert, observation, or route instruction.",
    }


def main(
    database: Path = DATABASE,
    raw_dir: Path = noaa.RAW_DIR,
    seed_dir: Path = SEED_DIR,
    *,
    download: bool = True,
) -> None:
    counties = list(SHORT_NAMES)
    if download:
        noaa.download_raw_files(counties, raw_dir)

    events = flood_events(counties, raw_dir, seed_dir)
    reports = flood_reports(counties, seed_dir)
    news = historic_news(counties, seed_dir)
    stations = noaa.weather_stations(counties)
    observations = noaa.weather_observations(counties, raw_dir)

    with open_database(database) as connection:
        replace_table(connection, "flood_events", events)
        replace_table(connection, "flood_reports", reports)
        replace_table(connection, "historic_news", news)
        replace_table(connection, "weather_stations", stations)
        replace_table(connection, "weather_observations", observations)
        record_sources(connection, [
            noaa.storm_events_source(len(events), raw_dir),
            noaa.weather_source(len(observations), counties, raw_dir),
            _reports_source(reports),
            _historic_news_source(news),
        ])

    mapped = sum(1 for e in events if e["lat"] is not None)
    dropped = sum(1 for e in events if e["geometry_note"])
    note = f", {dropped} bad coordinate(s) dropped" if dropped else ""
    print(f"flood_events: {len(events)} events across {len(counties)} counties ({mapped} mapped{note})")
    curated = sorted({r["county"] for r in reports})
    print(f"flood_reports: {len(reports)} reports (curated so far for: {', '.join(curated) or 'none'})")
    print(f"weather: {len(observations):,} daily readings from {len(stations)} stations")
    print("written to", database)


if __name__ == "__main__":
    main()
