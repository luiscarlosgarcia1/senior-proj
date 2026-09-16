"""Pipeline: pipeline/build_events.py — multi-county events/reports/rainfall."""

import json

import build_events


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
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(build_events, "DATA_DIR", data_dir)
    monkeypatch.setattr(build_events, "OUT_DIR", out_dir)
    monkeypatch.setattr(build_events, "COUNTIES", {slug: slug.title() for slug in counties})
    return data_dir, out_dir


def test_point_in_ring():
    ring = [(-98.6, 26.0), (-97.9, 26.0), (-97.9, 26.8), (-98.6, 26.8), (-98.6, 26.0)]
    assert build_events._point_in_ring(-98.2, 26.2, ring) is True
    assert build_events._point_in_ring(-97.0, 26.2, ring) is False


def test_near_county_allows_small_tolerance_but_not_far_away():
    ring = [(-98.6, 26.0), (-97.9, 26.0), (-97.9, 26.8), (-98.6, 26.8), (-98.6, 26.0)]
    just_outside = -97.9 + build_events.BOUNDARY_TOLERANCE_DEG / 2
    assert build_events._near_county(just_outside, 26.2, ring) is True  # within tolerance
    assert build_events._near_county(-90.0, 26.2, ring) is False  # nowhere close


def test_county_ring_reads_real_boundary(tmp_path, monkeypatch):
    data_dir, _ = _setup(tmp_path, monkeypatch, ["testville"])
    _write_county(data_dir, "testville", (-98.6, 26.0, -97.9, 26.8))
    ring = build_events._county_ring("testville")
    assert ring[0] == (-98.6, 26.0)
    assert len(ring) == 5


def test_build_events_merges_counties_and_drops_out_of_county_points(tmp_path, monkeypatch):
    data_dir, out_dir = _setup(tmp_path, monkeypatch, ["alpha", "beta"])
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

    total = build_events.build_events()
    assert total == 4

    fc = json.loads((out_dir / "flood-events.geojson").read_text())
    by_id = {f["properties"]["id"]: f for f in fc["features"]}

    assert by_id["in-1"]["geometry"] is not None
    assert by_id["in-1"]["properties"]["county"] == "alpha"
    assert by_id["bad-1"]["geometry"] is None
    assert "geometry_note" in by_id["bad-1"]["properties"]
    assert by_id["nogeo-1"]["geometry"] is None
    assert "geometry_note" not in by_id["nogeo-1"]["properties"]
    assert by_id["in-2"]["properties"]["county"] == "beta"


def test_build_reports_only_counts_public_reports_and_tags_county(tmp_path, monkeypatch):
    data_dir, out_dir = _setup(tmp_path, monkeypatch, ["alpha", "beta"])
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

    count = build_events.build_reports()
    assert count == 1

    data = json.loads((out_dir / "flood-reports.json").read_text())
    assert len(data["reports"]) == 1
    assert data["reports"][0]["county"] == "alpha"


def test_build_rainfall_merges_and_ranks_across_counties(tmp_path, monkeypatch):
    data_dir, out_dir = _setup(tmp_path, monkeypatch, ["alpha", "beta"])
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
    count = build_events.build_rainfall()
    assert count == 2

    data = json.loads((out_dir / "rainfall-records.json").read_text())
    days = data["days"]
    assert days[0]["county"] == "beta"
    assert days[0]["mm"] == 80.0
    assert days[1]["county"] == "alpha"
    assert days[1]["mm"] == 50.0


def test_event_type_from_summary():
    assert build_events._event_type("NOAA Storm Events flash flood record near X.") == "Flash flood"
    assert build_events._event_type("NOAA Storm Events heavy rain record near X.") == "Heavy rain"
    assert build_events._event_type("NOAA Storm Events flood record near X.") == "Flood"
