"""Turn the per-county flood-hazard layers into map-ready GeoJSON.

Reads `data/<county>-county/flood-hazard-layers/*.geojson`, then for each layer:

  * reprojects to EPSG:4326
  * clips FEMA NFHL to the true county boundary (drops bounding-box spillover)
  * assigns `relative_class` from `rgv_flood.severity`
  * dissolves adjacent polygons that share (county, source, category, class)
  * simplifies geometry to a map-scale tolerance

and writes the result plus `layers.json` into `src/rgv_flood/static/data/`,
which the Flask app serves as-is. Flood-evidence, drainage and insurance-claims
layers come from `evidence_layers.py`; layer descriptions from `layer_meta.py`.

Run:  uv run --group pipeline python pipeline/build_layers.py
Safe to re-run (overwrites its own outputs only).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Some FEMA NFHL records are single polygons with enormous ring counts; GDAL's
# GeoJSON reader rejects them by default. Lift the per-feature size cap before
# pyogrio / GDAL initializes.
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import evidence_layers
import geopandas as gpd
import pandas as pd
import pyogrio
from layer_io import DATA_DIR, OUT_DIR, write_layer
from layer_meta import LAYER_META

from rgv_flood.counties import NFHL_COUNTIES, SHORT_NAMES
from rgv_flood.severity import classify_fema_zone, relative_class_for

pyogrio.set_gdal_config_options({"OGR_GEOJSON_MAX_OBJ_SIZE": "0"})

# Geometry simplification tolerance in degrees. ~0.0003 deg ~= 33 m here.
# Regulatory layers (NFHL, the FIRM) keep the tighter tolerance; the TWDB modeled
# extent is contextual and enormously detailed, so it gets a coarser one.
TOLERANCE_REGULATORY = 0.0003
TOLERANCE_MODELED = 0.0015

# Columns that identify a hazard polygon; polygons sharing all of them are dissolved.
DISSOLVE_COLS = ["county_slug", "county", "source", "original_category", "relative_class"]


def _src(slug: str, name: str) -> Path:
    return DATA_DIR / f"{slug}-county" / "flood-hazard-layers" / name


def _drop_empty(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]


def _read(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.make_valid()
    return _drop_empty(gdf)


def _read_county(slug: str, filename: str) -> gpd.GeoDataFrame | None:
    """One county's layer file with its county columns set, or None if absent/empty."""
    path = _src(slug, filename)
    if not path.exists():
        return None
    gdf = _read(path)
    if gdf.empty:
        return None
    gdf["county_slug"] = slug
    gdf["county"] = SHORT_NAMES[slug]
    return gdf


def _stack(parts: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)


def _finish(gdf: gpd.GeoDataFrame, filename: str, tolerance: float = TOLERANCE_REGULATORY) -> int:
    """Dissolve, simplify and write a hazard layer."""
    gdf = gdf[[*(c for c in DISSOLVE_COLS if c in gdf.columns), "geometry"]]
    gdf = gdf.dissolve(by=[c for c in DISSOLVE_COLS if c in gdf.columns], as_index=False)
    gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
    gdf = _drop_empty(gdf)
    return write_layer(filename, gdf.to_json(drop_id=True), len(gdf))


def build_county_boundaries() -> int:
    parts = [_read_county(slug, "boundary.geojson")[["geometry", "county_slug", "county"]] for slug in SHORT_NAMES]
    out = _stack(parts)
    out["source"] = "US Census TIGER/Line 2023"
    out["original_category"] = "county boundary"
    out["relative_class"] = "uncategorized"
    return _finish(out, "county-boundaries.geojson")


def build_fema_nfhl() -> int:
    parts = []
    for slug in NFHL_COUNTIES:
        g = _read_county(slug, "fema-nfhl.geojson")
        g = _drop_empty(gpd.clip(g, _read_county(slug, "boundary.geojson").geometry.union_all()))
        subtypes = g.get("ZONE_SUBTY", [None] * len(g))
        g["source"] = "FEMA National Flood Hazard Layer"
        g["original_category"] = g["FLD_ZONE"].fillna("").astype(str)
        g["relative_class"] = [classify_fema_zone(zone, subtype) for zone, subtype in zip(g["FLD_ZONE"], subtypes, strict=True)]
        parts.append(g)
    return _finish(_stack(parts), "fema-nfhl.geojson")


def build_hidalgo_firm() -> int:
    g = _read_county("hidalgo", "hcdd1-firm-1981.geojson")
    zone = g["ZONE_LABEL"] if "ZONE_LABEL" in g.columns else g["ZONE"]
    g["source"] = "Hidalgo County DD No. 1 digitized 1981 FIRM"
    g["original_category"] = zone.fillna("").astype(str)
    g["relative_class"] = [classify_fema_zone(z) for z in g["original_category"]]
    return _finish(g, "hidalgo-firm-1981.geojson")


def build_twdb(freq: str, chance: str) -> int:
    source = "TWDB 2025 cursory floodplain"
    parts = []
    for slug in SHORT_NAMES:
        g = _read_county(slug, f"twdb-cursory-{freq}.geojson")
        if g is None:
            continue
        g["source"] = source
        g["original_category"] = chance
        g["relative_class"] = relative_class_for(source, chance)
        parts.append(g)
    return _finish(_stack(parts), f"twdb-cursory-{freq}.geojson", tolerance=TOLERANCE_MODELED)


def _primary_names(gdf: gpd.GeoDataFrame) -> list[str | None]:
    """Overture stores names as {"primary": ...}; take the primary one."""
    if "names" not in gdf.columns:
        return [None] * len(gdf)
    return [n.get("primary") if isinstance(n, dict) else None for n in gdf["names"]]


def build_overture_infrastructure(kind: str, filename: str) -> int:
    """Bridges/dams, kept as individual features (no dissolve, no severity:
    these are discrete structures at risk, not hazard zones)."""
    parts = []
    for slug in SHORT_NAMES:
        g = _read_county(slug, filename)
        if g is None:
            continue
        parts.append(g.assign(name=_primary_names(g))[["geometry", "county_slug", "county", "name"]])
    if not parts:
        return 0
    out = _drop_empty(_stack(parts).assign(source="Overture Maps Foundation", infrastructure_type=kind))
    return write_layer(filename, out.to_json(drop_id=True), len(out))


# Layer id -> builder. Order is the order layers appear in the sidebar.
BUILDERS = {
    "county-boundaries": build_county_boundaries,
    "fema-nfhl": build_fema_nfhl,
    "hidalgo-firm-1981": build_hidalgo_firm,
    "twdb-cursory-1in100": lambda: build_twdb("1in100", "1% annual chance"),
    "twdb-cursory-1in500": lambda: build_twdb("1in500", "0.2% annual chance"),
    "overture-bridges": lambda: build_overture_infrastructure("bridge", "overture-bridges.geojson"),
    "overture-dams": lambda: build_overture_infrastructure("dam", "overture-dams.geojson"),
    "hcdd1-flood-extents": evidence_layers.build_hcdd1_flood_extents,
    "hcdd1-flood-photos": evidence_layers.build_hcdd1_flood_photos,
    "hcdd1-drainage": evidence_layers.build_hcdd1_drainage,
    "hcdd1-bond-projects": evidence_layers.build_hcdd1_bond_projects,
    "nfip-claims-by-tract": evidence_layers.build_nfip_claims_by_tract,
}


def main() -> None:
    print("building map-ready layers ->", OUT_DIR)
    counts = {layer_id: build() for layer_id, build in BUILDERS.items()}

    layers = [
        {"id": layer_id, "file": f"{layer_id}.geojson", "feature_count": count, **LAYER_META[layer_id]}
        for layer_id, count in counts.items()
        if count
    ]
    manifest = {"generated_by": "pipeline/build_layers.py", "layers": layers}
    (OUT_DIR / "layers.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote layers.json with {len(layers)} layer(s)")


if __name__ == "__main__":
    main()
