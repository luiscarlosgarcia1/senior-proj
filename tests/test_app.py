import json

import pytest

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
