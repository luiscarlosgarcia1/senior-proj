#!/usr/bin/env python3
"""Import Overture Maps bridges and dams for the four RGV counties.

Public, fully reproducible (unlike flood-hazard-layers' FEMA/TWDB data, which
needs the sibling Flood Project/ working directory) -- Overture Maps
Foundation publishes open, versioned map data as cloud-native GeoParquet on
S3; queried here with the `overturemaps` package (anonymous S3 read, no
credentials or API key needed).

Only two `infrastructure`-theme classes are kept: bridges (impassable in a
flood -- this app's core theme) and dams (flood-control relevant). Everything
else in the theme (power grid, barriers, parking, street furniture, ...) is
generic and not flood-specific, so it's dropped rather than cluttering the map.

The RGV bounding box also covers a strip of Nuevo Leon, Mexico -- the border
follows the Rio Grande, so a rectangular bbox query can't avoid it. Every
feature is tested with shapely against each county's own TIGER boundary
polygon (data/<county>-county/flood-hazard-layers/boundary.geojson) and kept
only where it actually intersects a county -- the same fix already applied to
event coordinates in pipeline/build_events.py, applied here at the source.

Output is gitignored build output, not the tracked flood-hazard-layers files:
this source is fully public and scripted, unlike the FEMA/TWDB import.

Run:  uv run --group pipeline python pipeline/import_overture_infrastructure.py
Safe to re-run: re-downloads and overwrites just its own output files.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import shapely
from overturemaps import record_batch_reader
from shapely.geometry import shape

from rgv_flood.counties import COUNTIES

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# west, south, east, north -- a generous box around the four counties. This
# alone is NOT the exclusion boundary: every feature is also tested against
# each county's real polygon below, which is what actually keeps Mexico out.
RGV_BBOX = (-99.7, 25.6, -96.9, 27.1)

# Overture `infrastructure`-theme class -> output filename
KEPT_CLASSES = {
    "bridge": "overture-bridges.geojson",
    "dam": "overture-dams.geojson",
}


def _county_polygons() -> dict[str, shapely.Geometry]:
    """Each county's TIGER boundary, prepared so the many intersects tests below are fast."""
    polygons = {}
    for slug in COUNTIES:
        path = DATA_DIR / f"{slug}-county" / "flood-hazard-layers" / "boundary.geojson"
        polygons[slug] = shape(json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"])
        shapely.prepare(polygons[slug])
    return polygons


def _bridges_and_dams() -> Iterator[tuple[shapely.Geometry, dict]]:
    """Stream the `infrastructure` theme for the RGV bbox, yielding only bridges and dams."""
    reader = record_batch_reader("infrastructure", bbox=RGV_BBOX, stac=True)
    if reader is None:
        raise SystemExit("Overture returned no data for the RGV bounding box")

    for batch in reader:
        properties = [c for c in batch.schema.names if c not in ("geometry", "bbox")]
        geometries = shapely.from_wkb(batch.column("geometry").to_pylist())
        for geometry, row in zip(geometries, batch.select(properties).to_pylist(), strict=True):
            if row.get("class") in KEPT_CLASSES:
                yield geometry, row


def _feature(geometry: shapely.Geometry, row: dict) -> dict:
    return {
        "type": "Feature",
        "id": row.get("id"),
        "geometry": json.loads(shapely.to_geojson(geometry)),
        "properties": {k: v for k, v in row.items() if k != "id" and v is not None},
    }


def main() -> None:
    polygons = _county_polygons()
    by_county = {slug: {cls: [] for cls in KEPT_CLASSES} for slug in COUNTIES}
    downloaded = dropped = 0

    for geometry, row in _bridges_and_dams():
        downloaded += 1
        inside = [slug for slug, polygon in polygons.items() if polygon.intersects(geometry)]
        if not inside:
            dropped += 1  # outside all four counties: Mexico or a neighboring Texas county
            continue
        feature = _feature(geometry, row)
        for slug in inside:
            by_county[slug][row["class"]].append(feature)

    print(f"downloaded {downloaded} bridge/dam feature(s) from Overture for the RGV bbox")
    print(f"dropped {dropped} feature(s) outside all four county boundaries")

    for slug, classes in by_county.items():
        out_dir = DATA_DIR / f"{slug}-county" / "flood-hazard-layers"
        out_dir.mkdir(parents=True, exist_ok=True)
        for cls, features in classes.items():
            collection = {"type": "FeatureCollection", "features": features}
            (out_dir / KEPT_CLASSES[cls]).write_text(json.dumps(collection), encoding="utf-8")
        print(f"  [{slug}] " + ", ".join(f"{cls}s={len(features)}" for cls, features in classes.items()))


if __name__ == "__main__":
    main()
