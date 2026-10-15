"""Build every map layer and store it in the central database.

Hazard layers come from the seed GeoJSON in `data/seed/<county>/`. For each one this:

  * reprojects to EPSG:4326
  * clips FEMA NFHL to the true county boundary (drops bounding-box spillover)
  * assigns `relative_class` from `rgv_flood.severity`
  * dissolves adjacent polygons that share (county, source, category, class)
  * simplifies geometry to a map-scale tolerance

Each layer becomes one row of the `layers` table (see `database.py`): its
map-ready GeoJSON, which the Flask app serves as is, next to its description.
Bridges and dams are pulled from Overture Maps (`overture.py`); flood-evidence,
drainage and insurance-claims layers from their publishers
(`evidence_layers.py`); layer descriptions come from `layer_meta.py`.

Run:  uv run --group pipeline python pipeline/build_layers.py
Safe to re-run (replaces the `layers` table only).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

# Some FEMA NFHL records are single polygons with enormous ring counts; GDAL's
# GeoJSON reader rejects them by default. Lift the per-feature size cap before
# pyogrio / GDAL initializes.
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import evidence_layers
import geopandas as gpd
import overture
import pandas as pd
import pyogrio
import regional_layers
from database import MapLayer, open_database, record_sources, replace_table
from layer_meta import LAYER_META
from net import NETWORK_ERRORS, fetched_at
from paths import DATABASE, DOWNLOAD_CACHE, seed_file

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
    """One county's seed layer with its county columns set, or None if absent/empty."""
    path = seed_file(slug, filename)
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


def _as_layer(gdf: gpd.GeoDataFrame) -> MapLayer:
    return MapLayer(gdf.to_json(drop_id=True), len(gdf))


def _finish(gdf: gpd.GeoDataFrame, tolerance: float = TOLERANCE_REGULATORY) -> MapLayer:
    """Dissolve and simplify a hazard layer."""
    gdf = gdf[[*(c for c in DISSOLVE_COLS if c in gdf.columns), "geometry"]]
    gdf = gdf.dissolve(by=[c for c in DISSOLVE_COLS if c in gdf.columns], as_index=False)
    gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
    return _as_layer(_drop_empty(gdf))


def build_county_boundaries() -> MapLayer:
    parts = [_read_county(slug, "boundary.geojson")[["geometry", "county_slug", "county"]] for slug in SHORT_NAMES]
    out = _stack(parts)
    out["source"] = "US Census TIGER/Line 2023"
    out["original_category"] = "county boundary"
    out["relative_class"] = "uncategorized"
    return _finish(out)


def build_fema_nfhl() -> MapLayer:
    parts = []
    for slug in NFHL_COUNTIES:
        g = _read_county(slug, "fema-nfhl.geojson")
        g = _drop_empty(gpd.clip(g, _read_county(slug, "boundary.geojson").geometry.union_all()))
        subtypes = g.get("ZONE_SUBTY", [None] * len(g))
        g["source"] = "FEMA National Flood Hazard Layer"
        g["original_category"] = g["FLD_ZONE"].fillna("").astype(str)
        g["relative_class"] = [classify_fema_zone(zone, subtype) for zone, subtype in zip(g["FLD_ZONE"], subtypes, strict=True)]
        parts.append(g)
    return _finish(_stack(parts))


def build_hidalgo_firm() -> MapLayer:
    g = _read_county("hidalgo", "hcdd1-firm-1981.geojson")
    zone = g["ZONE_LABEL"] if "ZONE_LABEL" in g.columns else g["ZONE"]
    g["source"] = "Hidalgo County DD No. 1 digitized 1981 FIRM"
    g["original_category"] = zone.fillna("").astype(str)
    g["relative_class"] = [classify_fema_zone(z) for z in g["original_category"]]
    return _finish(g)


def build_twdb(freq: str, chance: str) -> MapLayer:
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
    return _finish(_stack(parts), tolerance=TOLERANCE_MODELED)


def build_overture_infrastructure(kind: str) -> MapLayer | None:
    """Bridges or dams, kept as individual features (no dissolve, no severity:
    these are discrete structures at risk, not hazard zones). A structure that
    spans two counties is listed under each."""
    rows = [
        {
            "geometry": geometry,
            "county_slug": slug,
            "county": SHORT_NAMES[slug],
            "name": (attributes.get("names") or {}).get("primary"),  # Overture: {"primary": ...}
        }
        for slug, geometry, attributes in overture.in_counties(overture.bridges_and_dams())
        if attributes["class"] == kind
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: list(SHORT_NAMES).index(row["county_slug"]))  # stable: county by county
    out = gpd.GeoDataFrame(rows, crs=4326)
    out["geometry"] = out.geometry.make_valid()
    return _as_layer(_drop_empty(out).assign(source="Overture Maps Foundation", infrastructure_type=kind))


# Layer id -> builder. Order is the order layers appear in the sidebar. A layer
# whose builder returns None (nothing to show) is left out.
BUILDERS = {
    "county-boundaries": build_county_boundaries,
    "fema-nfhl": build_fema_nfhl,
    "hidalgo-firm-1981": build_hidalgo_firm,
    "twdb-cursory-1in100": lambda: build_twdb("1in100", "1% annual chance"),
    "twdb-cursory-1in500": lambda: build_twdb("1in500", "0.2% annual chance"),
    "overture-bridges": lambda: build_overture_infrastructure("bridge"),
    "overture-dams": lambda: build_overture_infrastructure("dam"),
    "waterways": regional_layers.build_waterways,
    "flood-infrastructure": regional_layers.build_flood_infrastructure,
    "city-drainage": regional_layers.build_city_drainage,
    "hcdd1-flood-extents": evidence_layers.build_hcdd1_flood_extents,
    "hcdd1-flood-photos": evidence_layers.build_hcdd1_flood_photos,
    "hcdd1-drainage": evidence_layers.build_hcdd1_drainage,
    "hcdd1-bond-projects": evidence_layers.build_hcdd1_bond_projects,
    "flood-projects": regional_layers.build_flood_projects,
    "nws-flood-reports": regional_layers.build_nws_flood_reports,
    "nfip-claims-by-tract": evidence_layers.build_nfip_claims_by_tract,
}


def _row(layer_id: str, position: int, layer: MapLayer) -> dict:
    """A `layers` table row: the layer's GeoJSON plus its descriptive metadata."""
    meta = dict(LAYER_META[layer_id])
    geojson = layer.geojson.encode("utf-8")
    return {
        "id": layer_id,
        "position": position,
        "visualizations_json": json.dumps(meta.pop("visualizations", [])),
        **meta,
        "feature_count": layer.feature_count,
        # Compressed once here so the app can send it without spending CPU per
        # request. mtime=0 keeps the bytes the same from one build to the next.
        "geojson_gzip": gzip.compress(geojson, mtime=0),
        "etag": hashlib.sha256(geojson).hexdigest()[:32],
    }


# Layer id -> the download-cache folders its builder reads. Layers not listed
# are built from the seed files, which are not downloaded.
DOWNLOADED_INTO = {
    "overture-bridges": ("overture",),
    "overture-dams": ("overture",),
    "hcdd1-flood-extents": ("hcdd1",),
    "hcdd1-flood-photos": ("hcdd1",),
    "hcdd1-drainage": ("hcdd1",),
    "hcdd1-bond-projects": ("hcdd1",),
    "nfip-claims-by-tract": ("nfip", "tracts"),
    "waterways": ("tiger",),
    "flood-infrastructure": ("twdb",),
    "flood-projects": ("twdb",),
    "city-drainage": ("cities",),
    "nws-flood-reports": ("nws",),
}


def _source(layer_id: str, feature_count: int) -> dict:
    """The `data_sources` row for a layer, from the same metadata the app shows."""
    meta = LAYER_META[layer_id]
    downloads = [
        path
        for folder in DOWNLOADED_INTO.get(layer_id, ())
        for path in (DOWNLOAD_CACHE / folder).iterdir()
        if path.is_file()
    ]
    return {
        "id": f"layer:{layer_id}",
        "publisher": meta["source"],
        "dataset": meta["title"],
        "url": meta.get("source_url"),
        "retrieved_at": fetched_at(downloads),
        "record_count": feature_count,
        "notes": f"Vintage: {meta.get('vintage') or 'unknown'}. {meta.get('limitation') or ''}".strip(),
    }


def main(database: Path = DATABASE) -> None:
    print("building map layers ->", database)
    rows, skipped = [], []
    for position, (layer_id, build) in enumerate(BUILDERS.items()):
        try:
            layer = build()
        except NETWORK_ERRORS as error:
            # One publisher being down shouldn't cost the map every other layer.
            print(f"  [fail] {layer_id}: could not reach its source ({error})")
            skipped.append(layer_id)
            continue
        if layer is None or not layer.feature_count:
            continue
        row = _row(layer_id, position, layer)
        size, sent = len(layer.geojson.encode("utf-8")), len(row["geojson_gzip"])
        print(f"  {layer_id}: {layer.feature_count} features, {size / 1024:,.0f} KB ({sent / 1024:,.0f} KB gzipped)")
        rows.append(row)

    with open_database(database) as connection:
        replace_table(connection, "layers", rows)
        record_sources(connection, [_source(row["id"], row["feature_count"]) for row in rows])
    print(f"wrote {len(rows)} layer(s) to the layers table")
    if skipped:
        raise SystemExit(f"layers left out because their source could not be reached: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
