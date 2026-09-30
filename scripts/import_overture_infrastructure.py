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

Run:  uv run --group pipeline python scripts/import_overture_infrastructure.py
Safe to re-run: re-downloads and overwrites just its own output files.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import shapely
from overturemaps import record_batch_reader

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# west, south, east, north -- a generous box around the four counties. This
# alone is NOT the exclusion boundary: every feature is also tested against
# each county's real polygon below, which is what actually keeps Mexico out.
RGV_BBOX = (-99.7, 25.6, -96.9, 27.1)

COUNTIES = {
    "cameron": "Cameron",
    "hidalgo": "Hidalgo",
    "starr": "Starr",
    "willacy": "Willacy",
}

# Overture `infrastructure`-theme class -> (layer id, output filename)
KEPT_CLASSES = {
    "bridge": ("overture-bridges", "overture-bridges.geojson"),
    "dam": ("overture-dams", "overture-dams.geojson"),
}

RETRIEVED_AT = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _county_polygons() -> dict[str, shapely.Geometry]:
    polygons = {}
    for slug in COUNTIES:
        path = DATA_DIR / f"{slug}-county" / "flood-hazard-layers" / "boundary.geojson"
        fc = json.loads(path.read_text(encoding="utf-8"))
        polygons[slug] = shapely.geometry.shape(fc["features"][0]["geometry"])
    return polygons


def _fetch_bridge_and_dam_rows() -> list[dict]:
    """Stream the `infrastructure` theme for the RGV bbox, keeping only bridges/dams."""
    reader = record_batch_reader("infrastructure", bbox=RGV_BBOX, stac=True)
    if reader is None:
        raise SystemExit("Overture returned no data for the RGV bounding box")

    rows: list[dict] = []
    while True:
        try:
            batch = reader.read_next_batch()
        except StopIteration:
            break
        if batch.num_rows == 0:
            continue
        prop_cols = [c for c in batch.schema.names if c not in ("geometry", "bbox")]
        geometries = shapely.from_wkb(batch.column("geometry").to_pylist())
        props = batch.select(prop_cols).to_pylist()
        for geometry, row in zip(geometries, props):
            if row.get("class") in KEPT_CLASSES:
                rows.append({"geometry": geometry, "properties": row})
    return rows


def main() -> None:
    polygons = _county_polygons()
    rows = _fetch_bridge_and_dam_rows()
    print(f"downloaded {len(rows)} bridge/dam feature(s) from Overture for the RGV bbox")

    per_county: dict[str, dict[str, list[dict]]] = {
        slug: {cls: [] for cls in KEPT_CLASSES} for slug in COUNTIES
    }
    dropped_outside_counties = 0

    for row in rows:
        geometry = row["geometry"]
        props = row["properties"]
        cls = props["class"]
        matched_counties = [slug for slug, poly in polygons.items() if geometry.intersects(poly)]
        if not matched_counties:
            dropped_outside_counties += 1
            continue  # outside all four counties -- Mexico or a neighboring TX county
        feature = {
            "type": "Feature",
            "id": props.get("id"),
            "geometry": json.loads(shapely.to_geojson(geometry)),
            "properties": {k: v for k, v in props.items() if k != "id" and v is not None},
        }
        for slug in matched_counties:
            per_county[slug][cls].append(feature)

    print(f"dropped {dropped_outside_counties} feature(s) outside all four county boundaries")

    for slug, name in COUNTIES.items():
        out_dir = DATA_DIR / f"{slug}-county" / "flood-hazard-layers"
        out_dir.mkdir(parents=True, exist_ok=True)
        layers = []
        for cls, (layer_id, filename) in KEPT_CLASSES.items():
            features = per_county[slug][cls]
            fc = {"type": "FeatureCollection", "features": features}
            (out_dir / filename).write_text(json.dumps(fc), encoding="utf-8")
            layers.append({"id": layer_id, "file": filename, "feature_count": len(features)})

        manifest = {
            "county": name,
            "county_slug": slug,
            "source": "Overture Maps Foundation -- infrastructure theme",
            "retrieved_at": RETRIEVED_AT,
            "importer": "scripts/import_overture_infrastructure.py",
            "layers": layers,
        }
        (out_dir / "overture-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        counts = ", ".join(f"{layer['id']}={layer['feature_count']}" for layer in layers)
        print(f"  [{slug}] {counts} -> {out_dir}")


if __name__ == "__main__":
    main()
