"""API: live official alerts, the year-by-year claims history, data sources."""

from datetime import UTC, datetime

from database import open_database, replace_table


def _signal(native_id, source, *, county="hidalgo", geometry=None, provenance="official", state="active"):
    return {
        "source": source, "native_id": native_id, "provenance": provenance,
        "source_url": f"https://example.test/{native_id}", "source_publisher": "National Weather Service",
        "source_channel": "api", "summary": f"Summary of {native_id}", "source_attributes_json": "{}",
        "county_slugs_json": f'["{county}"]', "inclusion_basis": "source county field",
        "source_geometry_json": geometry, "geometry_absence_reason": None if geometry else "no geometry",
        "is_mappable": 1 if geometry else 0, "published_at": None, "effective_at": None,
        "source_updated_at": None, "expires_at": "2026-10-16T01:00:00Z", "first_seen_at": "2026-10-15T10:00:00Z",
        "last_seen_at": "2026-10-15T10:00:00Z", "retrieved_at": "2026-10-15T10:00:00Z", "lifecycle_state": state,
        "terminal_at": None, "terminal_reason": None, "absent_success_count": 0,
    }


POINT = '{"type":"Point","coordinates":[-98.2,26.2]}'


def _add_signals(database):
    with open_database(database) as connection:
        replace_table(connection, "live_signals", [
            _signal("warning-1", "nws", geometry=POINT),
            _signal("notice-1", "hidalgo-rss"),  # no geometry: listed, not mapped
            _signal("road-1", "drivetexas", county="cameron", geometry=POINT),
            _signal("public-1", "community", geometry=POINT, provenance="public-report"),  # never shown
            _signal("old-1", "nws", geometry=POINT, state="inactive"),  # expired
        ])
        replace_table(connection, "live_signal_runs", [
            {"run_id": 1, "source": "nws", "retrieved_at": "2026-10-15T10:00:00Z",
             "completed_at": "2026-10-15T10:00:05Z", "is_complete": 1, "received_count": 3, "error_message": None},
            {"run_id": 2, "source": "nws", "retrieved_at": "2026-10-15T10:15:00Z",
             "completed_at": "2026-10-15T10:15:04Z", "is_complete": 1, "received_count": 3, "error_message": None},
        ])


def test_live_signals_empty(api_client):
    assert api_client.get("/api/v1/live-signals").json() == {"refreshed_at": None, "signals": []}
    assert api_client.get("/api/v1/live-signals.geojson").json()["features"] == []


def test_live_signals_listed_with_refresh_time(api_client, fixture_db):
    _add_signals(fixture_db)

    body = api_client.get("/api/v1/live-signals").json()

    assert body["refreshed_at"] == "2026-10-15T10:15:04Z"
    assert {s["native_id"] for s in body["signals"]} == {"warning-1", "notice-1", "road-1"}


def test_live_signals_filtered_by_county(api_client, fixture_db):
    _add_signals(fixture_db)

    body = api_client.get("/api/v1/live-signals", params={"county": "cameron"}).json()

    assert [s["native_id"] for s in body["signals"]] == ["road-1"]


def test_live_signals_geojson_only_mappable(api_client, fixture_db):
    _add_signals(fixture_db)

    features = api_client.get("/api/v1/live-signals.geojson").json()["features"]

    assert {f["properties"]["native_id"] for f in features} == {"warning-1", "road-1"}


def test_history_all_counties_has_years_from_1978(api_client):
    body = api_client.get("/api/v1/history").json()

    assert body["first_year"] == 1978
    assert body["last_year"] == datetime.now(UTC).year - 1
    assert body["years"][0]["year"] == 1978
    assert body["years"][-1]["year"] == body["last_year"]
    assert body["totals"]["claims"] == 4


def test_history_county_totals(api_client):
    body = api_client.get("/api/v1/history", params={"county": "starr"}).json()

    assert body["totals"]["claims"] == 1
    assert body["totals"]["worst_year"] == 2020


def test_sources_include_built_at(api_client):
    body = api_client.get("/api/v1/sources").json()

    assert body["built_at"] == "2026-10-15T12:00:00Z"
    assert [s["id"] for s in body["sources"]] == ["noaa-storm-events", "layer:fema-nfhl"]
    assert body["sources"][0]["retrieved_at"] == "2026-09-16T04:30:40Z"
