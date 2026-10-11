"""Pipeline: pipeline/build_events.py — events, reports and weather into the database."""

import json
import sqlite3
from contextlib import closing

import build_events
import noaa
from shapely.geometry import shape
from test_noaa import storm_row, write_station_file, write_storm_file

HIDALGO_BOX = (-98.6, 26.0, -97.9, 26.8)


def _write_boundary(seed_dir, slug, bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    ring = [[lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max], [lon_min, lat_max], [lon_min, lat_min]]
    feature = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
    path = seed_dir / slug / "boundary.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))


def _event(**values):
    return {"id": "e-1", "county": "hidalgo", "source_lon": -98.2, "source_lat": 26.2, **values}


def test_near_county_allows_small_tolerance_but_not_far_away():
    county = shape({"type": "Polygon", "coordinates": [[(-98.6, 26.0), (-97.9, 26.0), (-97.9, 26.8), (-98.6, 26.8), (-98.6, 26.0)]]})
    just_outside = -97.9 + build_events.BOUNDARY_TOLERANCE_DEG / 2
    assert build_events._near_county(-98.2, 26.2, county) is True  # inside
    assert build_events._near_county(just_outside, 26.2, county) is True  # within tolerance
    assert build_events._near_county(-90.0, 26.2, county) is False  # nowhere close


def test_plot_keeps_a_point_inside_the_county_and_drops_one_outside():
    county = shape({"type": "Polygon", "coordinates": [[(-98.6, 26.0), (-97.9, 26.0), (-97.9, 26.8), (-98.6, 26.8), (-98.6, 26.0)]]})

    inside = build_events._plot(_event(), county)
    outside = build_events._plot(_event(source_lon=-90.0), county)
    no_point = build_events._plot(_event(source_lon=None, source_lat=None), county)

    assert (inside["lon"], inside["lat"], inside["geometry_note"]) == (-98.2, 26.2, None)
    assert (outside["lon"], outside["lat"]) == (None, None)
    assert "outside Hidalgo County" in outside["geometry_note"]
    assert outside["source_lon"] == -90.0  # what NOAA published is kept
    assert (no_point["lat"], no_point["geometry_note"]) == (None, None)


def test_flood_events_are_newest_first_across_counties(tmp_path):
    seed, raw = tmp_path / "seed", tmp_path / "raw"
    _write_boundary(seed, "hidalgo", HIDALGO_BOX)
    _write_boundary(seed, "cameron", (-97.9, 25.8, -97.1, 26.4))
    write_storm_file(raw, [
        storm_row(EVENT_ID="1"),
        storm_row(EVENT_ID="2", CZ_NAME="CAMERON", BEGIN_LON="-97.5", BEGIN_DATE_TIME="03-MAR-20 10:00:00"),
    ])

    events = build_events.flood_events(["hidalgo", "cameron"], raw, seed)

    assert [(e["id"], e["county"], e["date"]) for e in events] == [
        ("noaa-storm-events-2", "cameron", "2020-03-03"),
        ("noaa-storm-events-1", "hidalgo", "2018-06-21"),
    ]


def test_flood_reports_come_from_each_countys_seed_file(tmp_path):
    seed = tmp_path / "seed"
    report = {
        "record_id": "courthouse-closures",
        "record_kind": "public_report",
        "summary": "Roads closed downtown. Boat rescues were under way.",
        "location_text": "Weslaco, Hidalgo County, Texas",
        "event_start": "2018-06-20",
        "published_at": "2018-06-21",
        "source_publisher": "Hidalgo County, Texas",
        "source_channel": "local_government",
        "source_reference": {"kind": "source_url", "value": "https://example.test/notice"},
        "duplicate_group_id": "hidalgo-flood-2018-06",
    }
    (seed / "hidalgo").mkdir(parents=True)
    (seed / "hidalgo" / "public-reports.ndjson").write_text(json.dumps(report) + "\n")

    (row,) = build_events.flood_reports(["cameron", "hidalgo"], seed)  # cameron has no seed file

    assert row["id"] == "courthouse-closures"
    assert row["county"] == "hidalgo"
    assert row["headline"] == "Roads closed downtown."
    assert row["event_date"] == "2018-06-20"
    assert row["source_url"] == "https://example.test/notice"
    assert row["duplicate_group"] == "hidalgo-flood-2018-06"


def test_main_fills_the_database_and_can_be_rerun(tmp_path, monkeypatch):
    seed, raw, database = tmp_path / "seed", tmp_path / "raw", tmp_path / "generated" / "db.sqlite3"
    monkeypatch.setattr(build_events, "SHORT_NAMES", {"hidalgo": "Hidalgo"})
    _write_boundary(seed, "hidalgo", HIDALGO_BOX)
    write_storm_file(raw, [storm_row(EVENT_ID="1"), storm_row(EVENT_ID="2", BEGIN_LON="-90.0")])
    station = next(iter(noaa.STATIONS_BY_COUNTY["hidalgo"]))
    write_station_file(raw, "hidalgo", station, [f"{station},20180621,PRCP,1234,,,7,"])

    build_events.main(database, raw, seed, download=False)
    build_events.main(database, raw, seed, download=False)  # replaces its tables rather than adding to them

    with closing(sqlite3.connect(database)) as connection:
        counts = {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("flood_events", "flood_reports", "weather_stations", "weather_observations", "layers")
        }
        points = connection.execute("select lon, source_lon from flood_events order by id").fetchall()
        sources = dict(connection.execute("select id, record_count from data_sources"))
    assert counts == {
        "flood_events": 2,
        "flood_reports": 0,
        "weather_stations": len(noaa.STATIONS_BY_COUNTY["hidalgo"]),
        "weather_observations": 1,
        "layers": 0,
    }
    assert points == [(-98.2, -98.2), (None, -90.0)]  # the second point is outside the county: kept, not plotted
    assert sources == {"noaa-storm-events": 2, "noaa-ghcn-daily": 1, "local-public-reports": 0}
