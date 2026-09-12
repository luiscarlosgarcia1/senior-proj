"""Import validated canonical records into the GeoPackage."""

from __future__ import annotations

import json
import sqlite3

from .county_import import CountyImport
from .errors import BuildError
from .geopackage import canonical_json, gpkg_geometry
from .validation import iter_ndjson, validate_record


def import_records(
    connection: sqlite3.Connection,
    county: CountyImport,
    manifest: dict,
    seen_record_ids: set[str],
) -> None:
    """Validate and import every declared record set for one county collection."""
    for record_set in manifest.get("record_sets", []):
        records_dir = county.directory / record_set["path"]
        schema_path = county.directory / record_set["schema"]
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError) as error:
            raise BuildError(
                f"invalid record-set schema: {schema_path.relative_to(county.repository_root)}"
            ) from error
        for ndjson_path in sorted(records_dir.glob("*.ndjson")):
            artifact_id = county.source_artifacts[
                ndjson_path.relative_to(county.directory).as_posix()
            ]
            for line_number, record in iter_ndjson(ndjson_path, county.repository_root):
                context = (
                    f"{ndjson_path.relative_to(county.repository_root)}:{line_number}"
                )
                validate_record(record, schema, context)
                record_id = record.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise BuildError(
                        f"{ndjson_path.relative_to(county.repository_root)}:{line_number}: missing record_id"
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
                geometry = gpkg_geometry(geometry, context)
                connection.execute(
                    "INSERT INTO records(record_id, county_id, source_artifact_id, record_kind, source_publisher, source_channel, source_reference_kind, source_reference_value, event_start, event_end, published_at, location_text, location_precision, geometry_absence_reason, original_attributes_json, record_json, geometry) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record_id,
                        county.slug,
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
                        canonical_json(record.get("original_attributes"))
                        if "original_attributes" in record
                        else None,
                        canonical_json(record),
                        geometry,
                    ),
                )
                search_content = " ".join(
                    str(value)
                    for value in (
                        record.get("summary"),
                        record.get("original_content_reference"),
                        record.get("location_text"),
                        record.get("source_publisher"),
                        record.get("source_channel"),
                        source_reference.get("value"),
                        record.get("original_attributes"),
                    )
                    if value
                )
                connection.execute(
                    "INSERT INTO records_fts VALUES (?, ?, ?, ?)",
                    (
                        record_id,
                        county.slug,
                        record.get("record_kind", "unknown"),
                        search_content,
                    ),
                )
                if record.get("record_kind") == "weather_observation":
                    _import_weather_observation(connection, record, record_id, context)


def _import_weather_observation(
    connection: sqlite3.Connection, record: dict, record_id: str, context: str
) -> None:
    connection.execute(
        "INSERT INTO weather_observations(record_id, dataset_name, dataset_version_or_publication_date, retrieved_at, license_or_terms_note, coverage_geometry_absence_reason, observation_attributes_json, geometry) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record_id,
            record["dataset_name"],
            record["dataset_version_or_publication_date"],
            record["retrieved_at"],
            record["license_or_terms_note"],
            record.get("coverage_or_station_geometry_absence_reason"),
            canonical_json(record["original_attributes"]),
            gpkg_geometry(record.get("coverage_or_station_geometry"), context),
        ),
    )
