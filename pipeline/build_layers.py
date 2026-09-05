"""Turn the imported per-county flood-hazard layers into map-ready GeoJSON.

Reads `data/<county>-county/flood-hazard-layers/*.geojson` (the raw layers
imported from the Flood Project), then for each output layer:

  * reprojects to EPSG:4326
  * clips FEMA NFHL to the true county boundary (drops bounding-box spillover)
  * assigns `relative_class` from `rgv_flood.severity`
  * dissolves adjacent polygons that share (county, source, category, class)
  * simplifies geometry to a map-scale tolerance

and writes the result plus `layers.json` into `src/rgv_flood/static/data/`,
which the Flask app serves as-is.

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

import geopandas as gpd
import pandas as pd
import pyogrio

from rgv_flood.severity import classify_fema_zone, relative_class_for

pyogrio.set_gdal_config_options({"OGR_GEOJSON_MAX_OBJ_SIZE": "0"})

REPO_ROOT = Path(__file__).resolve().parents[1]
COUNTY_DIR = REPO_ROOT / "data"
OUT_DIR = REPO_ROOT / "src" / "rgv_flood" / "static" / "data"

# Geometry simplification tolerance in degrees. ~0.0003 deg ~= 33 m here.
# Regulatory layers (NFHL, the FIRM) keep the tighter tolerance; the TWDB modeled
# extent is contextual and enormously detailed, so it gets a coarser one.
TOLERANCE_REGULATORY = 0.0003
TOLERANCE_MODELED = 0.0015

COUNTIES = {"cameron": "Cameron", "hidalgo": "Hidalgo", "starr": "Starr", "willacy": "Willacy"}
NFHL_COUNTIES = ("cameron", "starr", "willacy")

KEEP_COLS = ["county_slug", "county", "source", "original_category", "relative_class", "geometry"]


def _src(slug: str, name: str) -> Path:
    return COUNTY_DIR / f"{slug}-county" / "flood-hazard-layers" / name


def _read(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]


def _boundary(slug: str) -> gpd.GeoDataFrame:
    return _read(_src(slug, "boundary.geojson"))


def _finish(gdf: gpd.GeoDataFrame, name: str, tolerance: float = TOLERANCE_REGULATORY) -> int:
    gdf = gdf[[c for c in KEEP_COLS if c in gdf.columns]].copy()
    gdf = gdf.dissolve(
        by=[c for c in ("county_slug", "county", "source", "original_category", "relative_class") if c in gdf.columns],
        as_index=False,
    )
    gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(gdf.to_json(drop_id=True), encoding="utf-8")
    kb = (OUT_DIR / name).stat().st_size / 1024
    print(f"  {name}: {len(gdf)} features, {kb:,.0f} KB")
    return len(gdf)


def build_county_boundaries() -> int:
    parts = []
    for slug, name in COUNTIES.items():
        g = _boundary(slug)[["geometry"]].copy()
        g["county_slug"] = slug
        g["county"] = name
        parts.append(g)
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    out["source"] = "US Census TIGER/Line 2023"
    out["original_category"] = "county boundary"
    out["relative_class"] = "uncategorized"
    return _finish(out, "county-boundaries.geojson")


def build_fema_nfhl() -> int:
    parts = []
    for slug in NFHL_COUNTIES:
        g = _read(_src(slug, "fema-nfhl.geojson"))
        boundary = _boundary(slug).geometry.union_all()
        g = gpd.clip(g, boundary)
        g = g[~g.geometry.is_empty & g.geometry.notna()]
        subty = g["ZONE_SUBTY"] if "ZONE_SUBTY" in g.columns else pd.Series([None] * len(g), index=g.index)
        g["county_slug"] = slug
        g["county"] = COUNTIES[slug]
        g["source"] = "FEMA National Flood Hazard Layer"
        g["original_category"] = g["FLD_ZONE"].fillna("").astype(str)
        g["relative_class"] = [classify_fema_zone(z, s) for z, s in zip(g["FLD_ZONE"], subty)]
        parts.append(g)
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    return _finish(out, "fema-nfhl.geojson")


def build_hidalgo_firm() -> int:
    g = _read(_src("hidalgo", "hcdd1-firm-1981.geojson"))
    label = g["ZONE_LABEL"] if "ZONE_LABEL" in g.columns else g["ZONE"]
    g["county_slug"] = "hidalgo"
    g["county"] = "Hidalgo"
    g["source"] = "Hidalgo County DD No. 1 digitized 1981 FIRM"
    g["original_category"] = label.fillna("").astype(str)
    g["relative_class"] = [classify_fema_zone(z) for z in g["original_category"]]
    return _finish(g, "hidalgo-firm-1981.geojson")


def build_twdb(freq: str, chance: str) -> int:
    parts = []
    for slug, name in COUNTIES.items():
        path = _src(slug, f"twdb-cursory-{freq}.geojson")
        if not path.exists():
            continue
        g = _read(path)
        if g.empty:
            continue
        g["county_slug"] = slug
        g["county"] = name
        g["source"] = "TWDB 2025 cursory floodplain"
        g["original_category"] = chance
        g["relative_class"] = relative_class_for("TWDB 2025 cursory floodplain", chance)
        parts.append(g)
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    return _finish(out, f"twdb-cursory-{freq}.geojson", tolerance=TOLERANCE_MODELED)


LAYER_META: dict[str, dict] = {
    "county-boundaries": {
        "title": "County boundaries",
        "source": "US Census TIGER/Line 2023",
        "vintage": "2023",
        "hazard_type": "n/a — study-area reference",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": "Geographic reference only. Not flood evidence.",
        "source_url": "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    },
    "fema-nfhl": {
        "title": "FEMA effective flood hazard (NFHL)",
        "source": "FEMA National Flood Hazard Layer",
        "vintage": "effective FIRM date varies by panel",
        "hazard_type": "effective regulatory flood hazard",
        "coverage": "Cameron, Starr, Willacy",
        "limitation": "No digital NFHL coverage for Hidalgo County. Clipped to county boundary; not a property-level determination.",
        "source_url": "https://msc.fema.gov/portal/home",
    },
    "hidalgo-firm-1981": {
        "title": "Hidalgo County historic flood zones (1981 FIRM)",
        "source": "Hidalgo County Drainage District No. 1 — digitized 1981 FIRM",
        "vintage": "1981 base map; some zones later revised by LOMR",
        "hazard_type": "historic local flood-zone reference",
        "coverage": "Hidalgo",
        "limitation": "44 years old; urban core largely undrawn. Legacy B/C zones shown as shaded-X / minimal by long-standing FEMA equivalence, but this is not current effective data.",
        "source_url": "https://www.hcdd1.org/page/floodplains",
    },
    "twdb-cursory-1in100": {
        "title": "TWDB modeled flood extent — 1% annual chance",
        "source": "TWDB 2025 cursory floodplain (Fathom 3m)",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
    "twdb-cursory-1in500": {
        "title": "TWDB modeled flood extent — 0.2% annual chance",
        "source": "TWDB 2025 cursory floodplain (Fathom 3m)",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
}


def main() -> None:
    print("building map-ready layers ->", OUT_DIR)
    counts = {
        "county-boundaries": build_county_boundaries(),
        "fema-nfhl": build_fema_nfhl(),
        "hidalgo-firm-1981": build_hidalgo_firm(),
        "twdb-cursory-1in100": build_twdb("1in100", "1% annual chance"),
        "twdb-cursory-1in500": build_twdb("1in500", "0.2% annual chance"),
    }

    layers = []
    for layer_id, meta in LAYER_META.items():
        file = f"{layer_id}.geojson"
        if counts.get(layer_id) and (OUT_DIR / file).exists():
            layers.append({"id": layer_id, "file": file, "feature_count": counts[layer_id], **meta})

    (OUT_DIR / "layers.json").write_text(
        json.dumps({"generated_by": "pipeline/build_layers.py", "layers": layers}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote layers.json with {len(layers)} layer(s)")


if __name__ == "__main__":
    main()
