"""Import validated canonical records into the GeoPackage."""

from __future__ import annotations

import json
import sqlite3

from jsonio import canonical_json

from .county_import import CountyImport
from .errors import BuildError
from .geopackage import gpkg_geometry
from .validation import iter_ndjson, record_validator, validate_record

RECORD_COLUMNS = (
    "record_id", "county_id", "source_artifact_id", "record_kind", "source_publisher", "source_channel",
    "source_reference_kind", "source_reference_value", "event_start", "event_end", "published_at",
    "location_text", "location_precision", "geometry_absence_reason", "original_attributes_json",
    "record_json", "geometry",
)
WEATHER_COLUMNS = (
    "record_id", "dataset_name", "dataset_version_or_publication_date", "retrieved_at",
    "license_or_terms_note", "coverage_geometry_absence_reason", "observation_attributes_json", "geometry",
)
# Record fields that feed full-text search, in the order they are concatenated.
SEARCHED_FIELDS = ("summary", "original_content_reference", "location_text", "source_publisher", "source_channel")


def _insert(connection: sqlite3.Connection, table: str, columns: tuple[str, ...], values: tuple) -> None:
    placeholders = ", ".join("?" * len(columns))
    connection.execute(f"INSERT INTO {table}({', '.join(columns)}) VALUES ({placeholders})", values)


def import_records(
    connection: sqlite3.Connection,
    county: CountyImport,
    manifest: dict,
    seen_record_ids: set[str],
) -> None:
    """Validate and import every declared record set for one county collection."""
    for record_set in manifest.get("record_sets", []):
        schema_path = county.directory / record_set["schema"]
        try:
            validator = record_validator(json.loads(schema_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as error:
            raise BuildError(
                f"invalid record-set schema: {schema_path.relative_to(county.repository_root)}"
            ) from error

        for ndjson_path in sorted((county.directory / record_set["path"]).glob("*.ndjson")):
            artifact_id = county.source_artifacts[ndjson_path.relative_to(county.directory).as_posix()]
            shown_path = ndjson_path.relative_to(county.repository_root)
            for line_number, record in iter_ndjson(ndjson_path, county.repository_root):
                context = f"{shown_path}:{line_number}"
                validate_record(record, validator, context)
                record_id = record.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise BuildError(f"{context}: missing record_id")
                if record_id in seen_record_ids:
                    raise BuildError(f"duplicate canonical record_id: {record_id}")
                seen_record_ids.add(record_id)
                _import_record(connection, county.slug, artifact_id, record, context)


def _import_record(
    connection: sqlite3.Connection, county_slug: str, artifact_id: str, record: dict, context: str
) -> None:
    """Insert one record, its search text, and (for weather) its observation row."""
    record_id = record["record_id"]
    record_kind = record.get("record_kind", "unknown")
    source_reference = record.get("source_reference") or {}
    # Events carry `geometry`; weather observations carry their station's instead.
    station_geometry = record.get("coverage_or_station_geometry")
    geometry = record.get("geometry", station_geometry)
    geometry_blob = gpkg_geometry(geometry, context)
    attributes_json = canonical_json(record.get("original_attributes")) if "original_attributes" in record else None

    _insert(connection, "records", RECORD_COLUMNS, (
        record_id,
        county_slug,
        artifact_id,
        record_kind,
        record.get("source_publisher"),
        record.get("source_channel"),
        source_reference.get("kind"),
        source_reference.get("value"),
        record.get("event_start"),
        record.get("event_end"),
        record.get("published_at"),
        record.get("location_text"),
        record.get("location_precision"),
        record.get("geometry_absence_reason", record.get("coverage_or_station_geometry_absence_reason")),
        attributes_json,
        canonical_json(record),
        geometry_blob,
    ))

    searched = (
        *(record.get(name) for name in SEARCHED_FIELDS),
        source_reference.get("value"),
        record.get("original_attributes"),
    )
    search_content = " ".join(str(value) for value in searched if value)
    connection.execute("INSERT INTO records_fts VALUES (?, ?, ?, ?)", (record_id, county_slug, record_kind, search_content))

    if record.get("record_kind") == "weather_observation":
        _insert(connection, "weather_observations", WEATHER_COLUMNS, (
            record_id,
            record["dataset_name"],
            record["dataset_version_or_publication_date"],
            record["retrieved_at"],
            record["license_or_terms_note"],
            record.get("coverage_or_station_geometry_absence_reason"),
            attributes_json,
            # Normally the same geometry as above; don't encode it a second time.
            geometry_blob if station_geometry is geometry else gpkg_geometry(station_geometry, context),
        ))
