"""Build a local GeoPackage from the canonical county collections.

The county collections under ``data/`` remain the source of record. This script
creates a queryable, reproducible local artifact from them; it does not feed the
Flask app or replace either existing precomputed-data builder.

Run: uv run --group pipeline python pipeline/build_county_collections_geopackage.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import struct
import tempfile
from collections.abc import Iterator
from pathlib import Path

from jsonschema import Draft202012Validator
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import shape
from shapely.ops import transform, unary_union

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT = DATA_DIR / "generated" / "county-collections.gpkg"
COUNTY_SLUGS = ("cameron", "hidalgo", "starr", "willacy")
EPSG_4326 = 4326


class BuildError(ValueError):
    """Raised when canonical input cannot be represented faithfully."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _gpkg_geometry(
    geometry: object, context: str, source_crs: str = "EPSG:4326"
) -> bytes | None:
    if geometry is None:
        return None
    try:
        parsed = shape(geometry)
    except Exception as error:
        raise BuildError(f"{context}: malformed GeoJSON geometry") from error
    if not parsed.is_valid:
        parsed = make_valid(parsed)
    if parsed.is_empty or not parsed.is_valid:
        raise BuildError(f"{context}: geometry is empty or cannot be made valid")
    if source_crs.upper() != "EPSG:4326":
        try:
            transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
            parsed = transform(transformer.transform, parsed)
        except Exception as error:
            raise BuildError(
                f"{context}: unsupported declared CRS {source_crs!r}"
            ) from error
    # GeoPackage binary header: GP, v0, little-endian/no envelope, then SRS ID.
    return b"GP" + bytes((0, 1)) + struct.pack("<i", EPSG_4326) + parsed.wkb


def _iter_ndjson(path: Path) -> Iterator[tuple[int, dict]]:
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise BuildError(
                f"{path.relative_to(REPO_ROOT)}:{line_number}: invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise BuildError(
                f"{path.relative_to(REPO_ROOT)}:{line_number}: record must be an object"
            )
        yield line_number, value


def _validate_record(record: dict, schema: dict, context: str) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=str)
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "record"
        raise BuildError(f"{context}: {location}: {error.message}")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA application_id = 1196437808;
        PRAGMA user_version = 10300;
        CREATE TABLE gpkg_spatial_ref_sys (
          srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
          organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
          definition TEXT NOT NULL, description TEXT
        );
        INSERT INTO gpkg_spatial_ref_sys VALUES
          ('Undefined Cartesian', -1, 'NONE', -1, 'undefined', 'undefined Cartesian coordinate reference system'),
          ('Undefined geographic', 0, 'NONE', 0, 'undefined', 'undefined geographic coordinate reference system'),
          ('WGS 84 geodetic', 4326, 'EPSG', 4326,
           'GEOGCS["WGS 84",DATUM["World Geodetic System 1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]',
           'longitude/latitude coordinates in decimal degrees');
        CREATE TABLE gpkg_contents (
          table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
          identifier TEXT UNIQUE, description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT '1970-01-01T00:00:00.000Z',
          min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER
        );
        CREATE TABLE gpkg_geometry_columns (
          table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
          srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
          PRIMARY KEY (table_name, column_name)
        );
        CREATE TABLE counties (
          county_id TEXT PRIMARY KEY, name TEXT NOT NULL, collection_path TEXT NOT NULL UNIQUE,
          manifest_json TEXT NOT NULL, geometry BLOB
        );
        CREATE TABLE source_artifacts (
          artifact_id TEXT PRIMARY KEY, county_id TEXT NOT NULL REFERENCES counties(county_id),
          relative_path TEXT NOT NULL, sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL,
          artifact_kind TEXT NOT NULL, UNIQUE(county_id, relative_path)
        );
        CREATE TABLE records (
          record_id TEXT PRIMARY KEY, county_id TEXT NOT NULL REFERENCES counties(county_id),
          source_artifact_id TEXT NOT NULL REFERENCES source_artifacts(artifact_id),
          record_kind TEXT NOT NULL, source_publisher TEXT, source_channel TEXT,
          source_reference_kind TEXT, source_reference_value TEXT, event_start TEXT, event_end TEXT,
          published_at TEXT, location_text TEXT, location_precision TEXT, geometry_absence_reason TEXT,
          original_attributes_json TEXT, record_json TEXT NOT NULL, geometry BLOB
        );
        CREATE TABLE weather_observations (
          record_id TEXT PRIMARY KEY REFERENCES records(record_id), dataset_name TEXT NOT NULL,
          dataset_version_or_publication_date TEXT NOT NULL, retrieved_at TEXT NOT NULL,
          license_or_terms_note TEXT NOT NULL, coverage_geometry_absence_reason TEXT,
          observation_attributes_json TEXT NOT NULL, geometry BLOB
        );
        CREATE TABLE spatial_layers (
          layer_id TEXT PRIMARY KEY, county_id TEXT NOT NULL REFERENCES counties(county_id),
          source_artifact_id TEXT NOT NULL REFERENCES source_artifacts(artifact_id),
          title TEXT, source_publisher TEXT, source_dataset TEXT, status TEXT, vintage TEXT,
          declared_crs TEXT, feature_count INTEGER, note TEXT, layer_json TEXT NOT NULL
        );
        CREATE TABLE layer_features (
          feature_id TEXT PRIMARY KEY, layer_id TEXT NOT NULL REFERENCES spatial_layers(layer_id),
          source_feature_index INTEGER NOT NULL, original_attributes_json TEXT NOT NULL,
          feature_json TEXT NOT NULL, geometry BLOB, UNIQUE(layer_id, source_feature_index)
        );
        """
    )
    for table_name, description in (
        ("counties", "Canonical county collections"),
        ("source_artifacts", "Exact canonical input artifacts and fingerprints"),
        ("records", "Documented events, public reports, and source records"),
        ("weather_observations", "Weather observations derived from canonical records"),
        ("spatial_layers", "Spatial-layer metadata from canonical manifests"),
        ("layer_features", "Spatial-layer features with original attributes"),
    ):
        connection.execute(
            "INSERT INTO gpkg_contents(table_name,data_type,identifier,description,srs_id) VALUES (?, 'attributes', ?, ?, 0)",
            (table_name, table_name, description),
        )
    for table_name in ("counties", "records", "weather_observations", "layer_features"):
        connection.execute(
            "UPDATE gpkg_contents SET data_type='features', srs_id=? WHERE table_name=?",
            (EPSG_4326, table_name),
        )
        connection.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?, 'geometry', 'GEOMETRY', ?, 0, 0)",
            (table_name, EPSG_4326),
        )


def _artifact_kind(relative_path: Path) -> str:
    if relative_path.suffix == ".geojson":
        return "spatial_layer"
    if relative_path.suffix == ".ndjson":
        return "record_set"
    if "/sources/" in f"/{relative_path.as_posix()}":
        return "source_note"
    return "collection_metadata"


def _build(connection: sqlite3.Connection) -> None:
    seen_record_ids: set[str] = set()
    county_boundaries: dict[str, list[tuple[object, str]]] = {
        slug: [] for slug in COUNTY_SLUGS
    }
    for slug in COUNTY_SLUGS:
        county_dir = DATA_DIR / f"{slug}-county"
        manifest_path = county_dir / "manifest.json"
        if not manifest_path.is_file():
            raise BuildError(
                f"missing canonical collection: {manifest_path.relative_to(REPO_ROOT)}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        county_name = manifest.get("geography", {}).get("name", slug.title())
        connection.execute(
            "INSERT INTO counties(county_id,name,collection_path,manifest_json) VALUES (?, ?, ?, ?)",
            (
                slug,
                county_name,
                county_dir.relative_to(REPO_ROOT).as_posix(),
                _canonical_json(manifest),
            ),
        )

        artifacts: dict[str, str] = {}
        for input_path in sorted(
            path for path in county_dir.rglob("*") if path.is_file()
        ):
            relative_path = input_path.relative_to(county_dir)
            artifact_id = f"{slug}:{relative_path.as_posix()}"
            data = input_path.read_bytes()
            connection.execute(
                "INSERT INTO source_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    slug,
                    relative_path.as_posix(),
                    hashlib.sha256(data).hexdigest(),
                    len(data),
                    _artifact_kind(relative_path),
                ),
            )
            artifacts[relative_path.as_posix()] = artifact_id

        for record_set in manifest.get("record_sets", []):
            records_dir = county_dir / record_set["path"]
            schema_path = county_dir / record_set["schema"]
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
            except (KeyError, OSError, json.JSONDecodeError) as error:
                raise BuildError(
                    f"invalid record-set schema: {schema_path.relative_to(REPO_ROOT)}"
                ) from error
            for ndjson_path in sorted(records_dir.glob("*.ndjson")):
                artifact_id = artifacts[ndjson_path.relative_to(county_dir).as_posix()]
                for line_number, record in _iter_ndjson(ndjson_path):
                    context = f"{ndjson_path.relative_to(REPO_ROOT)}:{line_number}"
                    _validate_record(record, schema, context)
                    record_id = record.get("record_id")
                    if not isinstance(record_id, str) or not record_id:
                        raise BuildError(
                            f"{ndjson_path.relative_to(REPO_ROOT)}:{line_number}: missing record_id"
                        )
                    if record_id in seen_record_ids:
                        raise BuildError(f"duplicate canonical record_id: {record_id}")
                    seen_record_ids.add(record_id)
                    source_reference = record.get("source_reference") or {}
                    geometry = record.get(
                        "geometry", record.get("coverage_or_station_geometry")
                    )
                    geometry_absence = record.get(
                        "geometry_absence_reason",
                        record.get("coverage_or_station_geometry_absence_reason"),
                    )
                    connection.execute(
                        "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            record_id,
                            slug,
                            artifact_id,
                            record.get("record_kind", "unknown"),
                            record.get("source_publisher"),
                            record.get("source_channel"),
                            source_reference.get("kind"),
                            source_reference.get("value"),
                            record.get("event_start"),
                            record.get("event_end"),
                            record.get("published_at"),
                            record.get("location_text"),
                            record.get("location_precision"),
                            geometry_absence,
                            _canonical_json(record.get("original_attributes"))
                            if "original_attributes" in record
                            else None,
                            _canonical_json(record),
                            _gpkg_geometry(geometry, context),
                        ),
                    )
                    if record.get("record_kind") == "weather_observation":
                        connection.execute(
                            "INSERT INTO weather_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                record_id,
                                record["dataset_name"],
                                record["dataset_version_or_publication_date"],
                                record["retrieved_at"],
                                record["license_or_terms_note"],
                                record.get(
                                    "coverage_or_station_geometry_absence_reason"
                                ),
                                _canonical_json(record["original_attributes"]),
                                _gpkg_geometry(
                                    record.get("coverage_or_station_geometry"),
                                    context,
                                ),
                            ),
                        )

        layers_manifest_path = county_dir / "flood-hazard-layers" / "manifest.json"
        layers_manifest = json.loads(layers_manifest_path.read_text(encoding="utf-8"))
        for layer in layers_manifest.get("layers", []):
            layer_id = f"{slug}:{layer['id']}"
            geojson_path = county_dir / "flood-hazard-layers" / layer["file"]
            source_artifact_id = artifacts[
                geojson_path.relative_to(county_dir).as_posix()
            ]
            connection.execute(
                "INSERT INTO spatial_layers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    layer_id,
                    slug,
                    source_artifact_id,
                    layer.get("title"),
                    layer.get("source_publisher"),
                    layer.get("source_dataset"),
                    layer.get("status"),
                    layer.get("vintage"),
                    layer.get("crs"),
                    layer.get("feature_count"),
                    layer.get("note"),
                    _canonical_json(layer),
                ),
            )
            try:
                features = json.loads(geojson_path.read_text(encoding="utf-8"))[
                    "features"
                ]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise BuildError(
                    f"{geojson_path.relative_to(REPO_ROOT)}: expected a GeoJSON FeatureCollection"
                ) from error
            for index, feature in enumerate(features):
                properties = feature.get("properties") or {}
                feature_identity = properties.get("id") or properties.get("feature_id")
                if not isinstance(feature_identity, str) or not feature_identity:
                    fingerprint = hashlib.sha256(
                        _canonical_json(feature).encode("utf-8")
                    ).hexdigest()[:24]
                    feature_identity = f"{layer_id}:{fingerprint}"
                feature_id = (
                    f"{layer_id}:{feature_identity}"
                    if not feature_identity.startswith(f"{layer_id}:")
                    else feature_identity
                )
                connection.execute(
                    "INSERT INTO layer_features VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        feature_id,
                        layer_id,
                        index,
                        _canonical_json(properties),
                        _canonical_json(feature),
                        _gpkg_geometry(
                            feature.get("geometry"),
                            f"{geojson_path.relative_to(REPO_ROOT)} feature {index}",
                            layer.get("crs", "EPSG:4326"),
                        ),
                    ),
                )
                if layer["id"] == "boundary" and feature.get("geometry") is not None:
                    county_boundaries[slug].append(
                        (shape(feature["geometry"]), layer.get("crs", "EPSG:4326"))
                    )
    for slug, entries in county_boundaries.items():
        if entries:
            geometries, crs = zip(*entries, strict=True)
            connection.execute(
                "UPDATE counties SET geometry=? WHERE county_id=?",
                (
                    _gpkg_geometry(
                        geometries[0].__geo_interface__
                        if len(geometries) == 1
                        else unary_union(geometries).__geo_interface__,
                        f"{slug} boundary",
                        crs[0],
                    ),
                    slug,
                ),
            )


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(temporary) as connection:
            _create_schema(connection)
            _build(connection)
            connection.commit()
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"GeoPackage path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    arguments = parser.parse_args()
    output = (
        arguments.output
        if arguments.output.is_absolute()
        else REPO_ROOT / arguments.output
    )
    try:
        build(output)
    except BuildError as error:
        raise SystemExit(f"GeoPackage build failed: {error}") from error
    print(
        f"Built {output.relative_to(REPO_ROOT) if output.is_relative_to(REPO_ROOT) else output}"
    )


if __name__ == "__main__":
    main()
