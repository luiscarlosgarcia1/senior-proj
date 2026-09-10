import hashlib
import json
import sqlite3
from pathlib import Path

import build_county_collections_geopackage as builder
import pytest


def _write_collection(root: Path, slug: str, record_id: str) -> None:
    county = root / "data" / f"{slug}-county"
    (county / "records" / "events").mkdir(parents=True)
    layers = county / "flood-hazard-layers"
    layers.mkdir()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "record_id",
            "record_kind",
            "source_reference",
            "geometry",
            "geometry_absence_reason",
        ],
        "properties": {
            name: {}
            for name in (
                "record_id",
                "record_kind",
                "source_reference",
                "geometry",
                "geometry_absence_reason",
            )
        },
    }
    (county / "schema.json").write_text(json.dumps(schema))
    (county / "manifest.json").write_text(
        json.dumps(
            {
                "geography": {"name": f"{slug.title()} County"},
                "record_sets": [{"path": "records/events", "schema": "schema.json"}],
            }
        )
    )
    record = {
        "record_id": record_id,
        "record_kind": "flood_event",
        "source_reference": {
            "kind": "source_url",
            "value": "https://example.test/source",
        },
        "geometry": None,
        "geometry_absence_reason": "No coordinate.",
    }
    (county / "records" / "events" / "records.ndjson").write_text(
        json.dumps(record) + "\n"
    )
    (layers / "manifest.json").write_text(
        json.dumps(
            {
                "layers": [
                    {"id": "boundary", "file": "boundary.geojson", "feature_count": 1}
                ]
            }
        )
    )
    feature = {
        "type": "Feature",
        "properties": {"name": slug},
        "geometry": {"type": "Point", "coordinates": [-98, 26]},
    }
    (layers / "boundary.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]})
    )


def _canonical_collections(tmp_path: Path, duplicate: bool = False) -> None:
    for index, slug in enumerate(builder.COUNTY_SLUGS):
        _write_collection(tmp_path, slug, "shared" if duplicate else f"event-{index}")


def test_build_creates_queryable_geopackage_from_canonical_collections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_collections(tmp_path)
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(builder, "DATA_DIR", tmp_path / "data")
    output = tmp_path / "output.gpkg"

    builder.build(output)

    with sqlite3.connect(output) as database:
        assert database.execute("select count(*) from counties").fetchone()[0] == 4
        assert database.execute("select count(*) from records").fetchone()[0] == 4
        assert (
            database.execute("select count(*) from spatial_layers").fetchone()[0] == 4
        )
        assert (
            database.execute(
                "select substr(geometry, 1, 8) from layer_features limit 1"
            ).fetchone()[0]
            == b"GP\x00\x01\xe6\x10\x00\x00"
        )
        record_artifact = database.execute(
            "select sha256 from source_artifacts where relative_path='records/events/records.ndjson' limit 1"
        ).fetchone()[0]
    source = (
        tmp_path / "data" / "cameron-county" / "records" / "events" / "records.ndjson"
    ).read_bytes()
    assert record_artifact == hashlib.sha256(source).hexdigest()
    first_build = output.read_bytes()
    builder.build(output)
    assert output.read_bytes() == first_build


def test_build_supports_indexed_text_and_spatial_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_collections(tmp_path)
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(builder, "DATA_DIR", tmp_path / "data")
    output = tmp_path / "output.gpkg"
    county = tmp_path / "data" / "cameron-county"
    schema_path = county / "schema.json"
    schema = json.loads(schema_path.read_text())
    schema["additionalProperties"] = True
    schema_path.write_text(json.dumps(schema))
    records_path = county / "records" / "events" / "records.ndjson"
    records = [json.loads(line) for line in records_path.read_text().splitlines()]
    records[0]["geometry"] = {"type": "Point", "coordinates": [-98, 26]}
    records[0]["event_start"] = "2026-01-01T00:00:00Z"
    records[0]["summary"] = "Severe rainfall caused localized flooding."
    records.append(
        {
            "record_id": "weather-0",
            "record_kind": "weather_observation",
            "source_reference": {"kind": "station", "value": "CAM-1"},
            "geometry": None,
            "geometry_absence_reason": "Weather coverage is represented separately.",
            "dataset_name": "Daily observations",
            "dataset_version_or_publication_date": "2026-01-01",
            "retrieved_at": "2026-01-02T00:00:00Z",
            "license_or_terms_note": "Public data.",
            "original_attributes": {"rainfall_inches": 1.5},
            "coverage_or_station_geometry": {
                "type": "Point",
                "coordinates": [-98.1, 26.1],
            },
        }
    )
    records_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    builder.build(output)

    with sqlite3.connect(output) as database:
        indexes = {
            row[1]
            for row in database.execute("select * from pragma_index_list('records')")
        }
        assert {"records_county_kind_date_idx", "records_event_start_idx"} <= indexes
        assert database.execute(
            "select record_id from records_fts where records_fts match 'severe'"
        ).fetchall() == [("event-0",)]
        assert database.execute(
            "select record_id from records where record_id = 'event-0'"
        ).fetchall() == [("event-0",)]
        assert database.execute(
            "select record_id from records where county_id = 'cameron' "
            "and record_kind = 'flood_event' and event_start = '2026-01-01T00:00:00Z'"
        ).fetchall() == [("event-0",)]
        provenance = database.execute(
            "select source_artifacts.sha256, substr(records.geometry, 1, 8) "
            "from records join source_artifacts "
            "on source_artifacts.artifact_id = records.source_artifact_id "
            "where records.record_id = 'event-0'"
        ).fetchone()
        assert provenance is not None
        assert provenance[0] == hashlib.sha256(records_path.read_bytes()).hexdigest()
        assert provenance[1] == b"GP\x00\x01\xe6\x10\x00\x00"
        assert (
            database.execute(
                "select feature_id from layer_features where layer_id = 'cameron:boundary'"
            )
            .fetchone()[0]
            .startswith("cameron:boundary:")
        )
        assert (
            database.execute(
                "select count(*) from rtree_layer_features_geometry "
                "where min_x <= -97 and max_x >= -99 and min_y <= 27 and max_y >= 25"
            ).fetchone()[0]
            == 4
        )
        assert database.execute(
            "select records.record_id from rtree_records_geometry "
            "join records on records.fid = rtree_records_geometry.id "
            "where min_x <= -97 and max_x >= -99 and min_y <= 27 and max_y >= 25"
        ).fetchall() == [("event-0",)]
        assert database.execute(
            "select weather_observations.record_id from rtree_weather_observations_geometry "
            "join weather_observations on weather_observations.fid = rtree_weather_observations_geometry.id"
        ).fetchall() == [("weather-0",)]


def test_build_preserves_existing_artifact_when_duplicate_identity_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_collections(tmp_path, duplicate=True)
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(builder, "DATA_DIR", tmp_path / "data")
    output = tmp_path / "output.gpkg"
    output.write_bytes(b"previous artifact")

    with pytest.raises(builder.BuildError, match="duplicate canonical record_id"):
        builder.build(output)

    assert output.read_bytes() == b"previous artifact"


def test_build_rejects_records_that_do_not_match_their_canonical_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_collections(tmp_path)
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(builder, "DATA_DIR", tmp_path / "data")
    broken_record = (
        tmp_path / "data" / "cameron-county" / "records" / "events" / "records.ndjson"
    )
    broken_record.write_text(json.dumps({"record_id": "event-0"}) + "\n")

    output = tmp_path / "output.gpkg"
    output.write_bytes(b"previous artifact")

    with pytest.raises(builder.BuildError, match="required property"):
        builder.build(output)

    assert output.read_bytes() == b"previous artifact"
