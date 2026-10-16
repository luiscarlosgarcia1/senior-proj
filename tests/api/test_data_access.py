"""data_access: every query, against the fixture database and with no database at all."""

from rgv_flood import data_access
from rgv_flood.db import Database


def test_flood_events_filters(fixture_db):
    db = Database(fixture_db)

    assert [e["id"] for e in data_access.flood_events(db)] == ["noaa-storm-events-1", "noaa-storm-events-2"]
    assert [e["id"] for e in data_access.flood_events(db, year="2018")] == ["noaa-storm-events-2"]
    assert data_access.flood_events(db, county_slug="cameron") == []
    assert data_access.flood_event_years(db) == ["2020", "2018"]


def test_history_by_year_totals(fixture_db):
    history = data_access.history_by_year(Database(fixture_db), "hidalgo", 2020)

    by_year = {y["year"]: y for y in history["years"]}
    hanna = by_year[2020]
    assert (hanna["claims"], hanna["paid"], hanna["flood_event"], hanna["busiest_month"]) == (2, 1500, "Hurricane Hanna", 7)
    assert hanna["claims_per_1000_policies"] == 2.0
    assert hanna["rain_inches"] == 15.0  # the average of the two complete gauges
    assert by_year[2018]["rain_inches"] is None  # the only gauge missed too many days
    assert history["totals"]["claims"] == 3


def test_event_context_queries(fixture_db):
    db = Database(fixture_db)
    event = data_access.flood_event(db, "noaa-storm-events-1")

    rain = data_access.rainfall_near_event(db, event)
    assert [g["name"] for g in rain["gauges"]][:2] == ["McAllen Airport", "Weslaco"]  # nearest first
    assert [r["id"] for r in data_access.reports_near_event(db, event)] == ["hanna-landfall", "hanna-recovery"]


def test_functions_tolerate_missing_database(tmp_path):
    db = Database(tmp_path / "not-built.sqlite3")

    assert data_access.available_layers(db) == []
    assert data_access.flood_events(db) == []
    assert data_access.flood_event(db, "x") is None
    assert data_access.flood_reports(db) == []
    assert data_access.rainfall_records(db) == []
    assert data_access.data_sources(db) == []
    assert data_access.active_official_signals(db) == []
    assert data_access.flood_events_geojson(db) is None
    assert data_access.history_by_year(db, None, 2020)["totals"]["claims"] == 0
