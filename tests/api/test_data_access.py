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
    assert (hanna["claims"], hanna["paid"], hanna["flood_event"]) == (2, 1500, "Hurricane Hanna")
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


def test_rank_correlation():
    assert data_access.rank_correlation([1, 2, 3, 4], [10, 20, 30, 1000]) == 1.0  # one extreme year doesn't matter
    assert data_access.rank_correlation([1, 2, 3], [3, 2, 1]) == -1.0
    assert data_access.rank_correlation([1, 2], [1, 2]) is None  # too few years
    assert data_access.rank_correlation([1, 2, 3], [5, 5, 5]) is None  # nothing varies


# ---- trends ----


def _trends(fixture_db, county=None, station=None, last_year=2021):
    return data_access.trends(Database(fixture_db), county, station, last_year)


def test_trends_events_per_year_include_empty_years(fixture_db):
    events = {y["year"]: y for y in _trends(fixture_db)["events_by_year"]}

    assert min(events) == data_access.TRENDS_FIRST_YEAR and max(events) == 2021
    assert events[2018] == {"year": 2018, "total": 1, "by_type": {"Flood": 1}}
    assert events[2019] == {"year": 2019, "total": 0, "by_type": {}}
    assert events[2020] == {"year": 2020, "total": 1, "by_type": {"Flash flood": 1}}


def test_trends_county_filter(fixture_db):
    cameron = _trends(fixture_db, county="cameron")

    assert all(y["total"] == 0 for y in cameron["events_by_year"])
    nws = {y["year"]: y for y in cameron["nws_by_year"]}
    assert nws[2020] == {"year": 2020, "total": 1, "by_kind": {"flood": 1}}
    assert min(nws) == data_access.NWS_FIRST_YEAR
    assert {y["year"]: y["total"] for y in _trends(fixture_db, county="hidalgo")["nws_by_year"]}[2020] == 1


def test_trends_station_series(fixture_db):
    result = _trends(fixture_db, county="hidalgo", station="USC00419588")  # Weslaco

    assert result["station"] == "USC00419588"
    assert [(y["year"], y["inches"], y["wettest_day_inches"], y["complete"]) for y in result["rain_years"]] == [
        (2020, 10.0, 5.0, True)
    ]
    months = {m["month"]: m for m in result["rain_months"]}
    assert months[6]["inches"] == 2.0 and months[7]["inches"] == 5.0
    assert months[8]["inches"] is None and months[8]["days_reported"] == 10  # too few days to count, and never zero


def test_trends_county_average_uses_only_complete_gauges(fixture_db):
    result = _trends(fixture_db, county="hidalgo")

    years = {y["year"]: y for y in result["rain_years"]}
    assert years[2020]["inches"] == 15.0 and years[2020]["complete"] is True
    assert years[2018]["inches"] is None and years[2018]["complete"] is False  # the only gauge missed too many days
    months = {m["month"]: m["inches"] for m in result["rain_months"]}
    assert months == {6: 2.0, 7: 7.5, 8: None}
    assert [s["name"] for s in result["stations"]] == ["McAllen Airport", "Weslaco"]


def test_trends_station_must_belong_to_the_county(fixture_db):
    for county, station in (("starr", "USC00419588"), ("hidalgo", "NOPE")):
        try:
            _trends(fixture_db, county=county, station=station)
        except data_access.UnknownStation:
            continue
        raise AssertionError(f"{station} in {county} should have been refused")


def test_trends_county_without_gauges_is_empty(fixture_db):
    result = _trends(fixture_db, county="cameron")

    assert result["stations"] == [] and result["rain_years"] == [] and result["rain_months"] == []


def test_trends_news_by_year(fixture_db):
    everything = _trends(fixture_db)
    hidalgo = _trends(fixture_db, county="hidalgo")

    assert everything["news_first_year"] == data_access.NEWS_FIRST_YEAR
    assert {y["year"]: y["count"] for y in everything["news_by_year"]} == {2018: 1, 2019: 0, 2020: 2, 2021: 0}
    assert {y["year"]: y["count"] for y in hidalgo["news_by_year"]}[2020] == 1


def test_trends_without_the_news_table(fixture_db):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("drop table news_articles")

    result = _trends(fixture_db)

    assert result["news_by_year"] == [] and result["news_first_year"] is None


def test_trends_database_built_before_monthly_rain_existed(fixture_db):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("drop table rainfall_station_months")

    result = _trends(fixture_db, county="hidalgo")

    assert result["rain_months"] == []
    assert result["rain_years"]  # the rest of the page still has its data
