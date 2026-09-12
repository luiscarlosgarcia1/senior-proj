"""Import canonical spatial-layer manifests and GeoJSON features."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from shapely.geometry import shape

from .county_import import CountyImport
from .errors import BuildError
from .geopackage import canonical_json, gpkg_geometry


def import_spatial_layers(
    connection: sqlite3.Connection,
    county: CountyImport,
) -> list[tuple[object, str]]:
    """Import one county's spatial layers and return its boundary geometries."""
    layers_manifest_path = county.directory / "flood-hazard-layers" / "manifest.json"
    layers_manifest = json.loads(layers_manifest_path.read_text(encoding="utf-8"))
    boundaries: list[tuple[object, str]] = []
    for layer in layers_manifest.get("layers", []):
        layer_id = f"{county.slug}:{layer['id']}"
        geojson_path = county.directory / "flood-hazard-layers" / layer["file"]
        source_artifact_id = county.source_artifacts[
            geojson_path.relative_to(county.directory).as_posix()
        ]
        connection.execute(
            "INSERT INTO spatial_layers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                layer_id,
                county.slug,
                source_artifact_id,
                layer.get("title"),
                layer.get("source_publisher"),
                layer.get("source_dataset"),
                layer.get("status"),
                layer.get("vintage"),
                layer.get("crs"),
                layer.get("feature_count"),
                layer.get("note"),
                canonical_json(layer),
            ),
        )
        try:
            features = json.loads(geojson_path.read_text(encoding="utf-8"))["features"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise BuildError(
                f"{geojson_path.relative_to(county.repository_root)}: expected a GeoJSON FeatureCollection"
            ) from error
        for index, feature in enumerate(features):
            _import_feature(
                connection,
                feature,
                index,
                layer,
                layer_id,
                geojson_path,
                county.repository_root,
            )
            if layer["id"] == "boundary" and feature.get("geometry") is not None:
                boundaries.append((shape(feature["geometry"]), layer.get("crs", "EPSG:4326")))
    return boundaries


def _import_feature(
    connection: sqlite3.Connection,
    feature: dict,
    index: int,
    layer: dict,
    layer_id: str,
    geojson_path: Path,
    repository_root: Path,
) -> None:
    properties = feature.get("properties") or {}
    feature_identity = properties.get("id") or properties.get("feature_id")
    if not isinstance(feature_identity, str) or not feature_identity:
        fingerprint = hashlib.sha256(canonical_json(feature).encode("utf-8")).hexdigest()[:24]
        feature_identity = f"{layer_id}:{fingerprint}"
    feature_id = (
        f"{layer_id}:{feature_identity}"
        if not feature_identity.startswith(f"{layer_id}:")
        else feature_identity
    )
    geometry = gpkg_geometry(
        feature.get("geometry"),
        f"{geojson_path.relative_to(repository_root)} feature {index}",
        layer.get("crs", "EPSG:4326"),
    )
    connection.execute(
        "INSERT INTO layer_features(feature_id, layer_id, source_feature_index, original_attributes_json, feature_json, geometry) VALUES (?, ?, ?, ?, ?, ?)",
        (feature_id, layer_id, index, canonical_json(properties), canonical_json(feature), geometry),
    )
