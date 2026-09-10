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

    with pytest.raises(builder.BuildError, match="required property"):
        builder.build(tmp_path / "output.gpkg")
