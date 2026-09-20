import json
from datetime import UTC, datetime

import pytest
from live_signals import LiveSignal, LiveSignalStore

from rgv_flood import create_app

EVENTS_FC = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-98.2, 26.2]},
            "properties": {
                "id": "noaa-storm-events-1",
                "date": "2020-07-25",
                "type": "Flash flood",
                "location": "WESLACO, Hidalgo County, Texas",
                "summary": "test event",
                "source_url": "https://example.test/1",
                "county": "hidalgo",
            },
        },
        {
            "type": "Feature",
            "geometry": None,
            "properties": {
                "id": "noaa-storm-events-2",
                "date": "2018-06-20",
                "type": "Flood",
                "location": "Hidalgo County, Texas",
                "summary": "test event without a point",
                "source_url": None,
                "county": "hidalgo",
            },
        },
    ],
}


@pytest.fixture()
def client(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "layers.json").write_text(json.dumps({"layers": []}))
    (data_dir / "flood-events.geojson").write_text(json.dumps(EVENTS_FC))
    (data_dir / "flood-reports.json").write_text(json.dumps({"reports": []}))
    (data_dir / "rainfall-records.json").write_text(
        json.dumps({"days": [{"date": "2025-03-28", "mm": 218.4, "inches": 8.6, "station": "Weslaco"}]})
    )
    app = create_app(
        {
            "TESTING": True,
            "MAP_DATA_DIR": data_dir,
            "FLOOD_EVENTS_FILE": data_dir / "flood-events.geojson",
            "FLOOD_REPORTS_FILE": data_dir / "flood-reports.json",
            "RAINFALL_FILE": data_dir / "rainfall-records.json",
        }
    )
    return app.test_client()


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


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


def test_missing_live_signals_is_404(client):
    assert client.get("/api/live-signals.geojson").status_code == 404


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
    client.application.config["LIVE_SIGNALS_DATABASE"] = database

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
    client.application.config["LIVE_SIGNALS_DATABASE"] = database

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


def test_rainfall_partial(client):
    res = client.get("/partials/rainfall")
    assert res.status_code == 200
    assert b"8.6 in" in res.data


def test_event_count_in_index(client):
    assert b'<span class="count">2</span>' in client.get("/").data
