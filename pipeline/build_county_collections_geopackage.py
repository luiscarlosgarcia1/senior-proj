"""Build a local GeoPackage from the canonical county collections.

The county collections under ``data/`` remain the source of record. This script
creates a queryable, reproducible local artifact from them; it does not feed the
Flask app or replace either existing precomputed-data builder.

Run: uv run --group pipeline python pipeline/build_county_collections_geopackage.py
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from county_collections_geopackage.county_import import CountyImport
from county_collections_geopackage.errors import BuildError
from county_collections_geopackage.geopackage import (
    canonical_json,
    create_schema,
    gpkg_geometry,
    register_spatial_functions,
)
from county_collections_geopackage.record_import import import_records
from county_collections_geopackage.spatial_layer_import import import_spatial_layers
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT = DATA_DIR / "generated" / "county-collections.gpkg"
COUNTY_SLUGS = ("cameron", "hidalgo", "starr", "willacy")


def _artifact_kind(relative_path: Path) -> str:
    if relative_path.suffix == ".geojson":
        return "spatial_layer"
    if relative_path.suffix == ".ndjson":
        return "record_set"
    if "/sources/" in f"/{relative_path.as_posix()}":
        return "source_note"
    return "collection_metadata"


def _import_artifacts(
    connection: sqlite3.Connection, county_dir: Path, slug: str
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for input_path in sorted(path for path in county_dir.rglob("*") if path.is_file()):
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
    return artifacts


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
            "INSERT INTO counties(county_id, name, collection_path, manifest_json) VALUES (?, ?, ?, ?)",
            (
                slug,
                county_name,
                county_dir.relative_to(REPO_ROOT).as_posix(),
                canonical_json(manifest),
            ),
        )
        county = CountyImport(
            directory=county_dir,
            slug=slug,
            source_artifacts=_import_artifacts(connection, county_dir, slug),
            repository_root=REPO_ROOT,
        )
        import_records(
            connection,
            county,
            manifest,
            seen_record_ids,
        )
        county_boundaries[slug] = import_spatial_layers(connection, county)
    _import_county_boundaries(connection, county_boundaries)


def _import_county_boundaries(
    connection: sqlite3.Connection, county_boundaries: dict[str, list[tuple[object, str]]]
) -> None:
    for slug, entries in county_boundaries.items():
        if entries:
            geometries, crs = zip(*entries, strict=True)
            connection.execute(
                "UPDATE counties SET geometry=? WHERE county_id=?",
                (
                    gpkg_geometry(
                        geometries[0].__geo_interface__
                        if len(geometries) == 1
                        else unary_union(geometries).__geo_interface__,
                        f"{slug} boundary",
                        crs[0],
                    ),
                    slug,
                ),
            )


def _replace_with_retry(temporary: Path, output: Path) -> None:
    """``os.replace`` with retries for Windows' transient post-write file lock.

    Immediately after a file is closed, Windows (antivirus real-time scanning in
    particular) can hold a brief exclusive lock on it, so the very next
    ``os.replace`` fails with ``PermissionError`` even though nothing in this
    process still has it open. POSIX has no such lock, so this never triggers
    there. Retrying with a short backoff is the standard workaround.
    """
    delays = (0.05, 0.1, 0.2)
    for delay in delays:
        try:
            os.replace(temporary, output)
            return
        except PermissionError:
            time.sleep(delay)
    # Rename still refused (observed with an existing destination that was just
    # read). Fall back to a copy + delete, which goes through different Win32
    # calls than MoveFileEx and isn't subject to the same lock.
    shutil.copyfile(temporary, output)
    os.remove(temporary)


def build(output: Path) -> None:
    """Build and atomically replace the GeoPackage artifact at ``output``."""
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        try:
            register_spatial_functions(connection)
            create_schema(connection)
            _build(connection)
            connection.commit()
        finally:
            # sqlite3.Connection's own context manager only commits/rolls back on
            # exit, it does not close the connection -- closing explicitly here
            # releases the OS file handle before the rename below. On Windows
            # (mandatory file locking) os.replace() fails on a still-open file;
            # POSIX would silently tolerate the leak, which is why this only
            # surfaces there.
            connection.close()
        gc.collect()  # drop any lingering cursor/statement refs holding the OS handle
        _replace_with_retry(temporary, output)
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
