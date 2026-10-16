import gzip
import json
from datetime import UTC, datetime

import pytest
from database import open_database, record_sources, replace_table
from fixture_db import (
    EVENTS,
    MCALLEN,
    READINGS,
    REPORTS,
    SOURCES,
    STATIONS,
    WESLACO,
    _claim,
    _gauge_year,
    _layer,
)
from live_signals import LiveSignal, LiveSignalStore

import rgv_flood
from rgv_flood import create_app


def _set_layers(client, *layers: dict) -> None:
    with open_database(client.application.config["DATABASE"]) as connection:
        replace_table(connection, "layers", list(layers))


@pytest.fixture()
def client(tmp_path):
    database = tmp_path / "rgv-flood.sqlite3"
    with open_database(database) as connection:
        replace_table(connection, "flood_events", EVENTS)
        replace_table(connection, "flood_reports", REPORTS)
        replace_table(connection, "weather_stations", STATIONS)
        replace_table(connection, "weather_observations", READINGS)
        record_sources(connection, SOURCES)
    app = create_app({"TESTING": True, "DATABASE": database, "LIVE_SIGNALS_SCHEDULER_ENABLED": False})
    return app.test_client()


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_app_starts_live_signal_scheduler_when_enabled(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class Scheduler:
        def __init__(self, commands, *, interval_seconds, lock_file):
            captured.update(
                commands=commands,
                interval_seconds=interval_seconds,
                lock_file=lock_file,
            )

        def start(self):
            return True

    monkeypatch.setattr(rgv_flood, "LiveSignalScheduler", Scheduler)
    database = tmp_path / "signals.sqlite3"
    lock_file = tmp_path / "scheduler.lock"

    app = create_app(
        {
            "LIVE_SIGNALS_SCHEDULER_ENABLED": True,
            "DATABASE": database,
            "LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS": 30,
            "LIVE_SIGNALS_SCHEDULER_LOCK_FILE": lock_file,
        }
    )

    assert app.extensions["live_signals_scheduler"].__class__ is Scheduler
    assert captured["interval_seconds"] == 30
    assert captured["lock_file"] == lock_file
    assert captured["commands"][0][-2:] == ("--output", str(database))


def test_debug_reloader_parent_does_not_start_live_signal_scheduler(monkeypatch):
    class Scheduler:
        def __init__(self, *args, **kwargs):
            raise AssertionError("the reloader parent must not create a scheduler")

    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.setattr(rgv_flood, "LiveSignalScheduler", Scheduler)

    app = create_app({"DEBUG": True, "LIVE_SIGNALS_SCHEDULER_ENABLED": True})

    assert "live_signals_scheduler" not in app.extensions


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"RGV Flood Impact Visualizer" in res.data
    assert b"Not for flood-insurance" in res.data


def test_all_four_counties_in_selector(client):
    body = client.get("/").data
    for name in (b"Cameron County", b"Hidalgo County", b"Starr County", b"Willacy County"):
        assert name in body


def test_reports_partial_lists_reports_and_says_when_a_county_has_none(client):
    assert client.get("/partials/reports").data.count(b'class="report"') == 3
    assert b"No reports" in client.get("/partials/reports?county_slug=starr").data


def test_unknown_county_is_404(client):
    assert client.get("/partials/reports?county_slug=nueces").status_code == 404


def test_missing_layer_is_404(client):
    assert client.get("/api/layers/nope.geojson").status_code == 404


def test_flood_events_geojson(client):
    res = client.get("/api/flood-events.geojson")
    assert res.status_code == 200
    assert len(res.json["features"]) == 2


def test_no_live_signals_before_the_first_poll(client):
    response = client.get("/api/live-signals.geojson")

    assert response.status_code == 200
    assert response.json["features"] == []
    assert b"No active official signals" in client.get("/partials/live-signals").data


def test_live_signals_endpoint_returns_only_mappable_official_signals(client, tmp_path):
    database = tmp_path / "live-signals.sqlite3"
    connection = __import__("sqlite3").connect(database)
    connection.executescript(
        """
        create table live_signals (
          source text, native_id text, source_url text, source_publisher text,
          source_channel text, summary text, source_attributes_json text,
          county_slugs_json text, inclusion_basis text, source_geometry_json text,
          published_at text, effective_at text, source_updated_at text, expires_at text,
          first_seen_at text, last_seen_at text, retrieved_at text, lifecycle_state text,
          provenance text, is_mappable integer
        );
        insert into live_signals values
          ('drivetexas:points', 'road-1', 'https://txdot.example/1', 'TxDOT', 'api',
           'Road closed', '{}', '["hidalgo"]', 'source county field',
           '{"type":"Point","coordinates":[-98.2,26.2]}', null, null, null, null,
           '2026-09-20T10:00:00Z', '2026-09-20T10:00:00Z', '2026-09-20T10:00:00Z',
           'active', 'official', 1),
          ('hidalgo-rss', 'notice-1', 'https://county.example/1', 'Hidalgo County', 'rss',
           'County notice', '{}', '["hidalgo"]', 'source feed scope', null,
           null, null, null, null, '2026-09-20T10:00:00Z', '2026-09-20T10:00:00Z',
           '2026-09-20T10:00:00Z', 'active', 'official', 0),
          ('https://api.weather.gov/alerts/active?area=TX', 'nws-1', 'https://weather.example/1',
           'National Weather Service', 'api', 'Flood warning', '{}', '["hidalgo"]',
           'source geocode', '{"type":"Polygon","coordinates":[[[-98.3,26.1],[-98.2,26.1],[-98.2,26.2],[-98.3,26.1]]]}',
           null, null, null, null, '2026-09-20T10:00:00Z', '2026-09-20T10:00:00Z',
           '2026-09-20T10:00:00Z', 'active', 'official', 1),
          ('community', 'report-1', 'https://example.test/1', 'Example', 'web',
           'Not official', '{}', '["hidalgo"]', 'source',
           '{"type":"Point","coordinates":[-98.2,26.2]}', null, null, null, null,
           '2026-09-20T10:00:00Z', '2026-09-20T10:00:00Z', '2026-09-20T10:00:00Z',
           'active', 'public-report', 1);
        """
    )
    connection.commit()
    connection.close()
    client.application.config["DATABASE"] = database

    response = client.get("/api/live-signals.geojson")

    assert response.status_code == 200
    assert {feature["properties"]["native_id"] for feature in response.json["features"]} == {"road-1", "nws-1"}


def test_live_signals_partial_keeps_unmappable_notices_as_source_links(client, tmp_path):
    database = tmp_path / "live-signals.sqlite3"
    store = LiveSignalStore(database)
    now = datetime(2026, 9, 20, 12, tzinfo=UTC)
    store.ingest(
        "hidalgo-rss",
        [
            LiveSignal(
                source="hidalgo-rss",
                native_id="notice-1",
                provenance="official",
                source_url="https://county.example/notices/1",
                source_publisher="Hidalgo County",
                source_channel="rss",
                summary="Public meeting notice",
                source_attributes={},
                county_slugs=("hidalgo",),
                inclusion_basis="feed_jurisdiction",
                source_geometry=None,
                geometry_absence_reason="The RSS item supplies no geometry.",
            )
        ],
        retrieved_at=now,
    )
    client.application.config["DATABASE"] = database

    response = client.get("/partials/live-signals?county_slug=hidalgo")

    assert response.status_code == 200
    assert b"Public meeting notice" in response.data
    assert b"https://county.example/notices/1" in response.data
    assert b"Notice only" in response.data


def test_events_partial_lists_and_filters(client):
    res = client.get("/partials/events")
    assert res.status_code == 200
    assert b"WESLACO" in res.data
    assert b"2 events" in res.data

    filtered = client.get("/partials/events?year=2020")
    assert b"WESLACO" in filtered.data
    assert b"1 event " in filtered.data


def test_events_partial_marks_locatable_rows(client):
    body = client.get("/partials/events").data
    assert b'data-lat="26.2"' in body  # the point event
    assert body.count(b"event-item") == 2  # both events listed


def test_events_partial_filters_by_county(client):
    assert b"2 events" in client.get("/partials/events?county_slug=hidalgo").data
    assert b"No events" in client.get("/partials/events?county_slug=cameron").data


def test_app_runs_before_the_database_is_built(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": tmp_path / "not-built-yet.sqlite3",
            "LIVE_SIGNALS_SCHEDULER_ENABLED": False,
        }
    )
    client = app.test_client()

    assert b"No layers yet" in client.get("/").data
    assert b"No events" in client.get("/partials/events").data
    assert b"No rainfall records" in client.get("/partials/rainfall").data
    assert client.get("/api/flood-events.geojson").status_code == 404
    assert client.get("/api/live-signals.geojson").status_code == 404
    assert client.get("/api/layers/fema-nfhl.geojson").status_code == 404
    assert not (tmp_path / "not-built-yet.sqlite3").exists()  # reading must not create it


def test_rainfall_partial_ranks_the_wettest_days(client):
    html = client.get("/partials/rainfall").get_data(as_text=True)

    assert html.index("8.6 in") < html.index("5.0 in") < html.index("2.0 in") < html.index("0.4 in")
    assert "0.0 in" not in html  # a dry day is not a record, and neither is the temperature reading
    assert "RGV gauges" in html


def test_rainfall_partial_shows_a_countys_own_records(client, monkeypatch):
    # With room for one record only, the overall list would be Weslaco's 8.6 in.
    monkeypatch.setattr("rgv_flood.data_access.RAINFALL_TOP_N", 1)

    html = client.get("/partials/rainfall?county_slug=starr").get_data(as_text=True)

    assert "2.0 in" in html and "Rio Grande City" in html
    assert "Starr County gauges" in html
    assert "8.6 in" not in html
    assert b"No rainfall records" in client.get("/partials/rainfall?county_slug=willacy").data


def test_event_context_shows_rain_at_the_nearest_gauges(client):
    html = client.get("/partials/events/noaa-storm-events-1/context").get_data(as_text=True)

    assert all(day in html for day in ("Jul 24", "Jul 25", "Jul 26"))  # the day before to the day after
    assert html.index("McAllen Airport") < html.index("Weslaco")  # 4 km away, then 23 km
    assert "1.00" in html and "5.00" in html
    assert "—" in html  # McAllen has no reading for the 24th or the 26th
    assert "Rio Grande City" not in html  # another county's gauge


def test_event_context_lists_every_report_of_a_flood_that_overlaps_the_event(client):
    html = client.get("/partials/events/noaa-storm-events-1/context").get_data(as_text=True)

    assert "Headline of hanna-landfall." in html
    assert "Headline of hanna-recovery." in html  # same flood, though dated six days after the event
    assert "weslaco-streets" not in html
    assert "not confirmed to describe this exact event" in html


def test_event_context_without_a_point_or_any_readings(client):
    html = client.get("/partials/events/noaa-storm-events-2/context").get_data(as_text=True)

    assert "No Hidalgo County gauge has a rainfall reading for these days" in html
    assert "Local reports" not in html
    assert client.get("/partials/events/no-such-event/context").status_code == 404


def test_sources_partial_lists_where_the_data_came_from(client):
    html = client.get("/partials/sources").get_data(as_text=True)

    assert html.index("Storm Events Database") < html.index("FEMA effective flood hazard")  # layers come last
    assert "1,425 records" in html and "downloaded 2026-09-16" in html
    assert "kept in the repository" in html  # the seed-file layer has no download date


def test_event_count_in_index(client):
    assert b'<span class="count">2</span>' in client.get("/").data


def test_source_card_lists_original_visualizations(client):
    visualizations = [{"title": "Publisher's own map", "url": "https://example.test/map"}]
    _set_layers(client, _layer("demo", title="Demo layer", visualizations_json=json.dumps(visualizations)))

    html = client.get("/partials/metadata/demo").get_data(as_text=True)

    assert "Original visualizations" in html
    assert 'href="https://example.test/map"' in html
    assert "Publisher&#39;s own map" in html


def test_source_card_omits_visualizations_when_none(client):
    _set_layers(client, _layer("plain"))

    html = client.get("/partials/metadata/plain").get_data(as_text=True)

    assert "Original visualizations" not in html


def test_layers_are_listed_in_sidebar_order(client):
    _set_layers(client, _layer("second", position=1), _layer("first", position=0))

    html = client.get("/").get_data(as_text=True)

    assert html.index('value="first"') < html.index('value="second"')


def test_layer_geojson_is_served_as_built_and_revalidates(client):
    geojson = '{"type":"FeatureCollection","features":[],"note":"kept as written"}'
    _set_layers(client, _layer("demo", geojson))

    response = client.get("/api/layers/demo.geojson")
    assert response.get_data(as_text=True) == geojson
    assert response.mimetype == "application/json"

    compressed = client.get("/api/layers/demo.geojson", headers={"Accept-Encoding": "gzip, br"})
    assert compressed.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(compressed.data).decode() == geojson
    assert compressed.headers["ETag"] == response.headers["ETag"]
    assert "Accept-Encoding" in compressed.headers["Vary"]

    repeat = client.get("/api/layers/demo.geojson", headers={"If-None-Match": response.headers["ETag"]})
    assert repeat.status_code == 304
    assert client.get("/api/layers/missing.geojson").status_code == 404


@pytest.fixture()
def history_client(client):
    with open_database(client.application.config["DATABASE"]) as connection:
        replace_table(connection, "nfip_claims", [
            _claim("a", "hidalgo", "2020-07-26", 1000, "Hurricane Hanna"),
            _claim("b", "hidalgo", "2020-07-27", 500, "Hurricane Hanna"),
            _claim("c", "starr", "2020-09-01", 250),
            _claim("d", "hidalgo", "2018-06-20", 100),
        ])
        replace_table(connection, "nfip_policies_by_year", [
            {"county": "hidalgo", "year": 2020, "policies": 1000},
            {"county": "starr", "year": 2020, "policies": 1000},
        ])
        replace_table(connection, "rainfall_station_years", [
            _gauge_year(WESLACO, 2020, 365, 2540, 1270),  # 10 in; wettest day 5 in
            _gauge_year(MCALLEN, 2020, 360, 5080, 254),  # 20 in
            _gauge_year(MCALLEN, 2018, 200, 99999, 9999),  # too many days missing to count
        ])
    return client


def test_history_counts_claims_and_rain_year_by_year(history_client):
    from rgv_flood import data_access
    from rgv_flood.db import Database

    history = data_access.history_by_year(Database(history_client.application.config["DATABASE"]), "hidalgo", 2020)

    by_year = {y["year"]: y for y in history["years"]}
    assert history["years"][0]["year"] == data_access.HISTORY_FIRST_YEAR
    hanna = by_year[2020]
    assert (hanna["claims"], hanna["paid"], hanna["flood_event"], hanna["busiest_month"]) == (2, 1500, "Hurricane Hanna", 7)
    assert hanna["claims_per_1000_policies"] == 2.0
    assert hanna["rain_inches"] == 15.0  # the average of the two complete gauges
    assert hanna["wettest_day_inches"] == 5.0
    assert hanna["noaa_flood_events"] == 1  # the 2020-07-25 flash flood
    assert by_year[2018]["rain_inches"] is None  # the only gauge missed too many days
    assert by_year[2018]["noaa_flood_events"] == 1
    assert by_year[1990]["noaa_flood_events"] is None  # before NOAA's flood records
    assert history["totals"] == {
        "claims": 3, "paid": 1600, "worst_year": 2020, "worst_year_claims": 2, "worst_year_event": "Hurricane Hanna",
    }


def test_rank_correlation():
    from rgv_flood.data_access import rank_correlation

    assert rank_correlation([1, 2, 3, 4], [10, 20, 30, 1000]) == 1.0  # one extreme year doesn't matter
    assert rank_correlation([1, 2, 3], [3, 2, 1]) == -1.0
    assert rank_correlation([1, 2], [1, 2]) is None  # too few years
    assert rank_correlation([1, 2, 3], [5, 5, 5]) is None  # nothing varies


def test_analysis_page_embeds_every_countys_history(history_client):
    html = history_client.get("/analysis").get_data(as_text=True)

    assert "Hurricane Hanna" in html
    histories = json.loads(html.split('id="history-data">')[1].split("</script>")[0])
    assert set(histories) == {"all", "cameron", "hidalgo", "starr", "willacy"}
    assert histories["all"]["totals"]["claims"] == 4
    assert histories["starr"]["totals"]["claims"] == 1
    assert b"Claims &amp; rainfall by year" in history_client.get("/").data


def test_analysis_page_before_the_database_is_built(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "none.sqlite3", "LIVE_SIGNALS_SCHEDULER_ENABLED": False})

    assert app.test_client().get("/analysis").status_code == 200
