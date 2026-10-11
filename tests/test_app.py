import json
from datetime import UTC, datetime

import pytest
from database import open_database, replace_table
from live_signals import LiveSignal, LiveSignalStore

import rgv_flood
from rgv_flood import create_app


def _event(event_id: str, date: str, **values) -> dict:
    return {
        "id": event_id,
        "county": "hidalgo",
        "date": date,
        "date_end": None,
        "type": "Flood",
        "location": "Hidalgo County, Texas",
        "precision": "county",
        "summary": "test event",
        "narrative": "test narrative",
        "source_url": "https://example.test/noaa",
        "source_lon": values.get("lon"),
        "source_lat": values.get("lat"),
        "geometry_note": None,
        "lon": None,
        "lat": None,
        **values,
    }


EVENTS = [
    _event(
        "noaa-storm-events-1",
        "2020-07-25",
        type="Flash flood",
        location="WESLACO, Hidalgo County, Texas",
        source_url="https://example.test/1",
        lon=-98.2,
        lat=26.2,
    ),
    _event("noaa-storm-events-2", "2018-06-20", summary="test event without a point"),
]
STATIONS = [
    {
        "station_id": "USC00419588",
        "county": "hidalgo",
        "name": "Weslaco",
        "lon": -97.97,
        "lat": 26.18,
        "elevation_m": 22.9,
        "source_url": "https://example.test/USC00419588.csv.gz",
    }
]


def _reading(date: str, element: str, value: int) -> dict:
    return {
        "station_id": "USC00419588", "date": date, "element": element, "value": value,
        "measurement_flag": None, "source_flag": "7", "observation_time_flag": None,
    }


# PRCP is tenths of a millimetre: 2184 is 218.4 mm, or 8.6 inches.
READINGS = [
    _reading("2025-03-28", "PRCP", 2184),
    _reading("2025-03-29", "PRCP", 100),
    _reading("2025-03-30", "PRCP", 0),  # a dry day is not a rainfall record
    _reading("2025-03-28", "TMAX", 9999),  # nor is a temperature
]


def _layer(layer_id: str, geojson: str = '{"type":"FeatureCollection","features":[]}', **values) -> dict:
    """A `layers` row with every column the app reads."""
    return {
        "id": layer_id,
        "position": 0,
        "title": layer_id.title(),
        "description": None,
        "source": "Somewhere",
        "vintage": None,
        "hazard_type": None,
        "coverage": None,
        "limitation": None,
        "source_url": None,
        "visualizations_json": "[]",
        "feature_count": 0,
        "geojson": geojson.encode(),
        "etag": f"etag-of-{layer_id}",
        **values,
    }


def _set_layers(client, *layers: dict) -> None:
    with open_database(client.application.config["DATABASE"]) as connection:
        replace_table(connection, "layers", list(layers))


@pytest.fixture()
def client(tmp_path):
    database = tmp_path / "rgv-flood.sqlite3"
    with open_database(database) as connection:
        replace_table(connection, "flood_events", EVENTS)
        replace_table(connection, "weather_stations", STATIONS)
        replace_table(connection, "weather_observations", READINGS)
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


def test_reports_partial_empty(client):
    res = client.get("/partials/reports")
    assert res.status_code == 200
    assert b"No reports" in res.data


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

    assert html.index("8.6 in") < html.index("0.4 in")  # 218.4 mm, then 10 mm
    assert html.count("rain-amount") == 2  # the dry day and the temperature reading are not listed
    assert "Weslaco" in html


def test_rainfall_partial_filters_by_county(client):
    assert b"8.6 in" in client.get("/partials/rainfall?county_slug=hidalgo").data
    assert b"No rainfall records" in client.get("/partials/rainfall?county_slug=starr").data


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

    repeat = client.get("/api/layers/demo.geojson", headers={"If-None-Match": response.headers["ETag"]})
    assert repeat.status_code == 304
    assert client.get("/api/layers/missing.geojson").status_code == 404
