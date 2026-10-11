"""Pipeline: pipeline/build_events.py — multi-county events/reports/rainfall."""

import json
import sqlite3
from contextlib import closing

import build_events
from shapely.geometry import shape


def _boundary_fc(bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    ring = [
        [lon_min, lat_min],
        [lon_max, lat_min],
        [lon_max, lat_max],
        [lon_min, lat_max],
        [lon_min, lat_min],
    ]
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}],
    }


def _write_ndjson(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r) for r in records)
    path.write_text(f"{text}\n" if records else "")


def _write_county(data_dir, slug, bbox, events=(), weather=()):
    root = data_dir / f"{slug}-county"
    (root / "flood-hazard-layers" / "boundary.geojson").parent.mkdir(parents=True, exist_ok=True)
    (root / "flood-hazard-layers" / "boundary.geojson").write_text(json.dumps(_boundary_fc(bbox)))
    _write_ndjson(root / "records" / "events-and-public-reports" / "noaa-storm-events.ndjson", events)
    _write_ndjson(root / "records" / "layers-and-weather" / "noaa-ghcn-daily-2000-2025.ndjson", weather)


def _event(record_id, geometry, county="testville", record_kind="flood_event", **overrides):
    record = {
        "record_id": record_id,
        "record_kind": record_kind,
        "event_start": "2020-07-25",
        "event_end": "2020-07-25",
        "location_text": f"SOMEWHERE, {county.title()} County, Texas",
        "summary": "NOAA Storm Events flood record near SOMEWHERE.",
        "source_reference": {"kind": "source_url", "value": "https://example.test"},
        "geometry": geometry,
    }
    record.update(overrides)
    return record


def _weather(date, mm, station="Test Station"):
    return {
        "original_attributes": {
            "date": date,
            "station_name": station,
            "observations": {"PRCP": {"value": mm * 10, "unit": "tenths of millimeters"}},
        }
    }


def _setup(tmp_path, monkeypatch, counties):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(build_events, "DATA_DIR", data_dir)
    monkeypatch.setattr(build_events, "COUNTY_NAMES", {slug: slug.title() for slug in counties})
    return data_dir


def test_near_county_allows_small_tolerance_but_not_far_away():
    county = shape({"type": "Polygon", "coordinates": [[(-98.6, 26.0), (-97.9, 26.0), (-97.9, 26.8), (-98.6, 26.8), (-98.6, 26.0)]]})
    just_outside = -97.9 + build_events.BOUNDARY_TOLERANCE_DEG / 2
    assert build_events._near_county(-98.2, 26.2, county) is True  # inside
    assert build_events._near_county(just_outside, 26.2, county) is True  # within tolerance
    assert build_events._near_county(-90.0, 26.2, county) is False  # nowhere close


def test_build_events_merges_counties_and_drops_out_of_county_points(tmp_path, monkeypatch):
    data_dir = _setup(tmp_path, monkeypatch, ["alpha", "beta"])
    _write_county(
        data_dir,
        "alpha",
        (-98.6, 26.0, -97.9, 26.8),
        events=[
            _event("in-1", {"type": "Point", "coordinates": [-98.2, 26.2]}, county="alpha"),
            _event("bad-1", {"type": "Point", "coordinates": [-90.0, 26.2]}, county="alpha"),
            _event("nogeo-1", None, county="alpha"),
        ],
    )
    _write_county(
        data_dir,
        "beta",
        (-90.5, 26.0, -89.9, 26.8),
        events=[_event("in-2", {"type": "Point", "coordinates": [-90.2, 26.2]}, county="beta")],
    )

    events = build_events.build_events()
    assert len(events) == 4
    by_id = {event["id"]: event for event in events}

    assert (by_id["in-1"]["lon"], by_id["in-1"]["lat"]) == (-98.2, 26.2)
    assert by_id["in-1"]["county"] == "alpha"
    assert by_id["bad-1"]["lat"] is None
    assert "outside Alpha County" in by_id["bad-1"]["geometry_note"]
    assert by_id["nogeo-1"]["lat"] is None
    assert by_id["nogeo-1"]["geometry_note"] is None
    assert by_id["in-2"]["county"] == "beta"


def test_build_reports_only_counts_public_reports_and_tags_county(tmp_path, monkeypatch):
    data_dir = _setup(tmp_path, monkeypatch, ["alpha", "beta"])
    _write_county(
        data_dir,
        "alpha",
        (-98.6, 26.0, -97.9, 26.8),
        events=[
            _event("ev-1", None, county="alpha"),
            _event("rep-1", None, county="alpha", record_kind="public_report", published_at="2020-07-25"),
        ],
    )
    _write_county(data_dir, "beta", (-90.5, 26.0, -89.9, 26.8), events=[])

    reports = build_events.build_reports()

    assert len(reports) == 1
    assert reports[0]["county"] == "alpha"


def test_build_rainfall_merges_and_ranks_across_counties(tmp_path, monkeypatch):
    data_dir = _setup(tmp_path, monkeypatch, ["alpha", "beta"])
    _write_county(
        data_dir,
        "alpha",
        (-98.6, 26.0, -97.9, 26.8),
        weather=[_weather("2020-07-25", 50.0), _weather("2020-07-26", 10.0)],
    )
    _write_county(
        data_dir,
        "beta",
        (-90.5, 26.0, -89.9, 26.8),
        weather=[_weather("2021-03-01", 80.0)],
    )

    monkeypatch.setattr(build_events, "RAINFALL_TOP_N", 2)
    days, rain_days = build_events.build_rainfall()

    assert rain_days == 3
    assert [(day["county"], day["mm"]) for day in days] == [("beta", 80.0), ("alpha", 50.0)]


def test_main_fills_the_app_database_and_can_be_rerun(tmp_path, monkeypatch):
    data_dir = _setup(tmp_path, monkeypatch, ["alpha"])
    _write_county(
        data_dir,
        "alpha",
        (-98.6, 26.0, -97.9, 26.8),
        events=[
            _event("in-1", {"type": "Point", "coordinates": [-98.2, 26.2]}, county="alpha"),
            _event("rep-1", None, county="alpha", record_kind="public_report"),
        ],
        weather=[_weather("2020-07-25", 50.0)],
    )
    database = tmp_path / "generated" / "app.sqlite3"

    build_events.main(database)
    build_events.main(database)  # replaces its tables rather than adding to them

    with closing(sqlite3.connect(database)) as connection:
        counts = {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("flood_events", "flood_reports", "rainfall_records", "layers")
        }
        point = connection.execute("select lon, lat from flood_events").fetchone()
    assert counts == {"flood_events": 1, "flood_reports": 1, "rainfall_records": 1, "layers": 0}
    assert point == (-98.2, 26.2)


def test_event_type_from_summary():
    assert build_events._event_type("NOAA Storm Events flash flood record near X.") == "Flash flood"
    assert build_events._event_type("NOAA Storm Events heavy rain record near X.") == "Heavy rain"
    assert build_events._event_type("NOAA Storm Events flood record near X.") == "Flood"
