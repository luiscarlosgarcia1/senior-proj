"""Pipeline: pipeline/build_events.py coordinate handling."""

import build_events


def _event(record_id, geometry, summary="NOAA Storm Events flood record near X."):
    return {
        "record_id": record_id,
        "record_kind": "flood_event",
        "event_start": "2020-07-25",
        "event_end": "2020-07-25",
        "location_text": "MC ALLEN, Hidalgo County, Texas",
        "summary": summary,
        "source_reference": {"kind": "source_url", "value": "https://example.test"},
        "geometry": geometry,
    }


def test_in_county_box():
    assert build_events._in_county_box(-98.23, 26.20) is True  # McAllen
    assert build_events._in_county_box(-97.72, 26.20) is False  # near Harlingen


def test_build_events_drops_out_of_county_points(tmp_path, monkeypatch):
    monkeypatch.setattr(build_events, "OUT_DIR", tmp_path)
    records = [
        _event("in-1", {"type": "Point", "coordinates": [-98.20, 26.20]}),
        _event("bad-1", {"type": "Point", "coordinates": [-97.7167, 26.20]}),
        _event("nogeo-1", None),
    ]
    build_events.build_events(records)

    fc = __import__("json").loads((tmp_path / "flood-events.geojson").read_text())
    by_id = {f["properties"]["id"]: f for f in fc["features"]}

    assert by_id["in-1"]["geometry"] is not None
    assert by_id["bad-1"]["geometry"] is None
    assert "geometry_note" in by_id["bad-1"]["properties"]
    assert by_id["nogeo-1"]["geometry"] is None
    assert "geometry_note" not in by_id["nogeo-1"]["properties"]


def test_event_type_from_summary():
    assert build_events._event_type("NOAA Storm Events flash flood record near X.") == "Flash flood"
    assert build_events._event_type("NOAA Storm Events heavy rain record near X.") == "Heavy rain"
    assert build_events._event_type("NOAA Storm Events flood record near X.") == "Flood"
