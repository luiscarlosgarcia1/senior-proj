"""GeoPackage schema and geometry encoding primitives."""

from __future__ import annotations

import json
import sqlite3
import struct

from pyproj import Transformer
from shapely import from_wkb, make_valid
from shapely.geometry import shape
from shapely.ops import transform

from .errors import BuildError

EPSG_4326 = 4326


def canonical_json(value: object) -> str:
    """Encode JSON deterministically so successive builds have identical bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def gpkg_geometry(
    geometry: object, context: str, source_crs: str = "EPSG:4326"
) -> bytes | None:
    """Encode a valid GeoJSON geometry as EPSG:4326 GeoPackage binary."""
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
    return b"GP" + bytes((0, 1)) + struct.pack("<i", EPSG_4326) + parsed.wkb


def register_spatial_functions(connection: sqlite3.Connection) -> None:
    """Register the geometry-bound functions required by GeoPackage RTree triggers."""
    def coordinate(position: int):
        def value(geometry: bytes | None) -> float | None:
            if geometry is None:
                return None
            return from_wkb(geometry[8:]).bounds[position]

        return value

    connection.create_function("ST_IsEmpty", 1, lambda geometry: geometry is None)
    connection.create_function("ST_MinX", 1, coordinate(0))
    connection.create_function("ST_MinY", 1, coordinate(1))
    connection.create_function("ST_MaxX", 1, coordinate(2))
    connection.create_function("ST_MaxY", 1, coordinate(3))


def create_schema(connection: sqlite3.Connection) -> None:
    """Create the fixed, queryable GeoPackage schema and its spatial indexes."""
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
        CREATE TABLE gpkg_extensions (
          table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,
          definition TEXT NOT NULL, scope TEXT NOT NULL,
          CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
        );
        CREATE TABLE counties (
          fid INTEGER PRIMARY KEY, county_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, collection_path TEXT NOT NULL UNIQUE,
          manifest_json TEXT NOT NULL, geometry BLOB
        );
        CREATE TABLE source_artifacts (
          artifact_id TEXT PRIMARY KEY, county_id TEXT NOT NULL REFERENCES counties(county_id),
          relative_path TEXT NOT NULL, sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL,
          artifact_kind TEXT NOT NULL, UNIQUE(county_id, relative_path)
        );
        CREATE TABLE records (
          fid INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE, county_id TEXT NOT NULL REFERENCES counties(county_id),
          source_artifact_id TEXT NOT NULL REFERENCES source_artifacts(artifact_id),
          record_kind TEXT NOT NULL, source_publisher TEXT, source_channel TEXT,
          source_reference_kind TEXT, source_reference_value TEXT, event_start TEXT, event_end TEXT,
          published_at TEXT, location_text TEXT, location_precision TEXT, geometry_absence_reason TEXT,
          original_attributes_json TEXT, record_json TEXT NOT NULL, geometry BLOB
        );
        CREATE TABLE weather_observations (
          fid INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE REFERENCES records(record_id), dataset_name TEXT NOT NULL,
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
          fid INTEGER PRIMARY KEY, feature_id TEXT NOT NULL UNIQUE, layer_id TEXT NOT NULL REFERENCES spatial_layers(layer_id),
          source_feature_index INTEGER NOT NULL, original_attributes_json TEXT NOT NULL,
          feature_json TEXT NOT NULL, geometry BLOB, UNIQUE(layer_id, source_feature_index)
        );
        CREATE INDEX records_county_kind_date_idx
          ON records(county_id, record_kind, event_start, published_at);
        CREATE INDEX records_event_start_idx ON records(event_start);
        CREATE INDEX spatial_layers_county_idx ON spatial_layers(county_id);
        CREATE INDEX layer_features_layer_idx ON layer_features(layer_id);
        CREATE VIRTUAL TABLE records_fts USING fts5(
          record_id UNINDEXED, county_id UNINDEXED, record_kind, content
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
    for table_name in ("records", "weather_observations", "layer_features"):
        connection.execute(
            f"CREATE VIRTUAL TABLE rtree_{table_name}_geometry "
            "USING rtree(id, min_x, max_x, min_y, max_y)"
        )
        connection.execute(
            "INSERT INTO gpkg_extensions VALUES (?, 'geometry', 'gpkg_rtree_index', ?, 'write-only')",
            (table_name, "http://www.geopackage.org/spec120/#extension_rtree"),
        )
        connection.executescript(
            f"""
            CREATE TRIGGER rtree_{table_name}_geometry_insert AFTER INSERT ON {table_name}
            WHEN NEW.geometry NOT NULL AND NOT ST_IsEmpty(NEW.geometry)
            BEGIN
              INSERT OR REPLACE INTO rtree_{table_name}_geometry
              VALUES (NEW.fid, ST_MinX(NEW.geometry), ST_MaxX(NEW.geometry), ST_MinY(NEW.geometry), ST_MaxY(NEW.geometry));
            END;
            CREATE TRIGGER rtree_{table_name}_geometry_update AFTER UPDATE OF geometry ON {table_name}
            BEGIN
              DELETE FROM rtree_{table_name}_geometry WHERE id = OLD.fid;
              INSERT OR REPLACE INTO rtree_{table_name}_geometry
              SELECT NEW.fid, ST_MinX(NEW.geometry), ST_MaxX(NEW.geometry), ST_MinY(NEW.geometry), ST_MaxY(NEW.geometry)
              WHERE NEW.geometry NOT NULL AND NOT ST_IsEmpty(NEW.geometry);
            END;
            CREATE TRIGGER rtree_{table_name}_geometry_delete AFTER DELETE ON {table_name}
            BEGIN
              DELETE FROM rtree_{table_name}_geometry WHERE id = OLD.fid;
            END;
            """
        )
