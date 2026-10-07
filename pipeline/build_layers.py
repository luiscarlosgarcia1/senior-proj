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


def _infra_name(gdf: gpd.GeoDataFrame) -> pd.Series:
    if "names" not in gdf.columns:
        return pd.Series([None] * len(gdf), index=gdf.index)
    return gdf["names"].apply(lambda v: v.get("primary") if isinstance(v, dict) else None)


def build_overture_infrastructure(kind: str, filename: str) -> int:
    """Bridges/dams: kept as individual features (no dissolve, no severity --
    these are discrete structures at risk, not hazard zones)."""
    parts = []
    for slug, name in COUNTIES.items():
        path = _src(slug, filename)
        if not path.exists():
            continue
        g = _read(path)
        if g.empty:
            continue
        names = _infra_name(g)
        g = g[["geometry"]].copy()
        g["county_slug"] = slug
        g["county"] = name
        g["name"] = names
        parts.append(g)
    if not parts:
        return 0
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    out["source"] = "Overture Maps Foundation"
    out["infrastructure_type"] = kind
    out = out[~out.geometry.is_empty & out.geometry.notna()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / filename).write_text(out.to_json(drop_id=True), encoding="utf-8")
    kb = (OUT_DIR / filename).stat().st_size / 1024
    print(f"  {filename}: {len(out)} features, {kb:,.0f} KB")
    return len(out)


# ---- Hidalgo flood evidence, drainage and NFIP claims -----------------------
# Inputs come from scripts/fetch_ml_inputs.py (data/ml/raw/, gitignored). Every
# builder here skips quietly when its raw files are missing, so a fresh clone
# that hasn't run the fetch script still builds the original layers.

ML_RAW = REPO_ROOT / "data" / "ml" / "raw"
HCDD1_DIR = ML_RAW / "hcdd1"
# W, S, E, N around the four counties; drops photos with stray GPS tags.
RGV_AREA = (-99.3, 25.8, -97.0, 26.9)

STATUS_NAMES = {
    "PD": "Pre-design", "Pre-Design": "Pre-design", "D": "Design", "Design": "Design",
    "C": "Construction", "Costruction": "Construction", "Construction": "Construction",
    "CL": "Complete", "Complete": "Complete",
}


def _hcdd1(name: str) -> list[dict]:
    path = HCDD1_DIR / f"{name}.geojson"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("features", [])


def _round_coords(coords, digits: int = 5):
    if isinstance(coords[0], (int, float)):
        return [round(c, digits) for c in coords[:2]]
    return [_round_coords(c, digits) for c in coords]


def _write_features(filename: str, features: list[dict]) -> int:
    if not features:
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": features}
    (OUT_DIR / filename).write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    print(f"  {filename}: {len(features)} features, {(OUT_DIR / filename).stat().st_size / 1024:,.0f} KB")
    return len(features)


def _feature(geometry: dict, properties: dict, tolerance: float = 0.0) -> dict | None:
    from shapely.geometry import mapping, shape

    if not geometry:
        return None
    if tolerance:
        geom = shape(geometry).simplify(tolerance, preserve_topology=True)
        if geom.is_empty:
            return None
        geometry = mapping(geom)
    geometry = {"type": geometry["type"], "coordinates": _round_coords(geometry["coordinates"])}
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def build_hcdd1_flood_extents() -> int:
    """Mapped flooded areas HCDD1 recorded for six past events (2008-2020).

    HCDD1 labels each event with an inch range (4"-10", 8"-14", ...). It is not
    stated whether that is rainfall or flood depth, so the label is passed
    through verbatim and never interpreted.
    """
    events = [
        ("flood_extent_2008_4to10in", 2008, '4"–10"'),
        ("flood_extent_2010_3to6in", 2010, '3"–6"'),
        ("flood_extent_2015_1to8in", 2015, '1"–8"'),
        ("flood_extent_2018_4to18in", 2018, '4"–18"'),
        ("flood_extent_2019_4to10in", 2019, '4"–10"'),
        ("flood_extent_2020_8to14in", 2020, '8"–14"'),
    ]
    features = []
    for name, year, label in events:
        for f in _hcdd1(name):
            feat = _feature(
                f.get("geometry"),
                {"overlay_type": "flood_extent", "year": year, "hcdd1_label": label,
                 "county": "Hidalgo", "source": "Hidalgo County Drainage District No. 1"},
                tolerance=0.00003,
            )
            if feat:
                features.append(feat)
    return _write_features("hcdd1-flood-extents.geojson", features)


def build_hcdd1_flood_photos() -> int:
    """Geotagged field photos taken during four flood responses. Only where, when
    and which event is kept -- not the internal file paths or camera heading."""
    sets = [
        ("flood_photos_2018_june", "June 2018"),
        ("flood_photos_2018_sept", "September 2018"),
        ("flood_photos_2019_june", "June 2019"),
        ("flood_photos_2020_hanna", "Hurricane Hanna 2020"),
        ("hanna_geotagged_photos", "Hurricane Hanna 2020"),
    ]
    west, south, east, north = RGV_AREA
    features = []
    for name, event in sets:
        for f in _hcdd1(name):
            geom = f.get("geometry")
            if not geom or geom.get("type") != "Point":
                continue
            x, y = geom["coordinates"][:2]
            if not (west < x < east and south < y < north):
                continue
            taken = (f["properties"].get("DateTime") or "")[:16].replace(":", "-", 2)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(x, 5), round(y, 5)]},
                "properties": {"overlay_type": "flood_photo", "event": event, "taken": taken},
            })
    return _write_features("hcdd1-flood-photos.geojson", features)


def build_hcdd1_drainage() -> int:
    """Drainage-district network: channels, detention ponds, gates and pumps."""
    features = []
    for f in _hcdd1("drainage_system"):
        p = f["properties"]
        feat = _feature(
            f.get("geometry"),
            {"overlay_type": "drainage", "kind": "channel",
             "name": p.get("Name") or p.get("AKA") or "Drainage channel",
             "owner": p.get("OwnOrMaint") or p.get("Owner") or ""},
            tolerance=0.00002,
        )
        if feat:
            features.append(feat)
    for f in _hcdd1("future_system"):
        p = f["properties"]
        feat = _feature(
            f.get("geometry"),
            {"overlay_type": "drainage", "kind": "planned_channel",
             "name": p.get("Name") or p.get("Syst_Name") or "Planned channel",
             "owner": p.get("Status") or ""},
            tolerance=0.00002,
        )
        if feat:
            features.append(feat)
    for f in _hcdd1("detention_ponds"):
        p = f["properties"]
        acres = p.get("Acreage")
        feat = _feature(
            f.get("geometry"),
            {"overlay_type": "drainage", "kind": "detention_pond",
             "name": p.get("Name") or "Detention pond",
             "owner": p.get("Exist_Prop") or "",
             "acres": round(acres, 1) if isinstance(acres, (int, float)) else None},
            tolerance=0.00002,
        )
        if feat:
            features.append(feat)
    for f in _hcdd1("gates_pumps_new"):
        p = f["properties"]
        gate_type = (p.get("gate_type") or "").strip()
        is_pump = "pump" in gate_type.lower() or bool((p.get("pump_no") or "").strip())
        feat = _feature(
            f.get("geometry"),
            {"overlay_type": "drainage", "kind": "pump" if is_pump else "gate",
             "name": (p.get("alias") or p.get("gate_id") or "Structure").strip(),
             "owner": gate_type},
        )
        if feat:
            features.append(feat)
    return _write_features("hcdd1-drainage.geojson", features)


def build_hcdd1_bond_projects() -> int:
    """Drainage-improvement projects funded by the 2012, 2018 and 2023 bonds --
    the district's record of infrastructure updates, with status and dates."""

    def year(ms) -> int | None:
        if not isinstance(ms, (int, float)):
            return None
        from datetime import UTC, datetime

        return datetime.fromtimestamp(ms / 1000, UTC).year

    features = []
    for name, program in (("bond_2012", "2012 bond"), ("bond_2018", "2018 bond"), ("bond_2023", "2023 bond")):
        for f in _hcdd1(name):
            p = f["properties"]
            status = STATUS_NAMES.get(p.get("Proj_Status") or p.get("ProjStatus") or "", "")
            title = p.get("ProjAreaNm") or p.get("Name") or p.get("NAME") or "Drainage project"
            desc = (p.get("Description") or p.get("Descript") or p.get("Summary") or "").strip()
            feat = _feature(
                f.get("geometry"),
                {"overlay_type": "bond_project", "program": program, "name": title.strip(),
                 "status": status, "description": desc[:400],
                 "start_year": year(p.get("Actl_Start")), "end_year": year(p.get("Actl_End")),
                 "precinct": str(p.get("Precinct") or "")},
                tolerance=0.00002,
            )
            if feat:
                features.append(feat)
    return _write_features("hcdd1-bond-projects.geojson", features)


def build_nfip_claims_by_tract() -> int:
    """NFIP flood-insurance claims per census tract, all four counties.

    Raw counts only: the policy file (needed to turn counts into a rate) is a
    separate, slower download, so tracts with many insured homes read high.

    About a third of claims carry pre-2020 (2010-vintage) tract numbers, many
    for tracts that were later split. Those are spread across the 2023 tracts
    that replaced them, weighted by overlapping area, rather than dropped.
    """
    claims_path = ML_RAW / "nfip" / "nfip_claims_v3.ndjson"
    tracts_zip = ML_RAW / "tracts" / "tl_2023_48_tract.zip"
    tracts10_zip = ML_RAW / "tracts" / "tl_2010_48_tract10.zip"
    if not claims_path.exists() or not tracts_zip.exists():
        return 0

    def blank() -> dict:
        return {"claims": 0.0, "paid": 0.0, "moved": 0.0, "years": set(), "events": {}}

    by_geoid: dict[str, dict] = {}
    for line in claims_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        claim = json.loads(line)
        geoid = str(claim.get("censusGeoid") or "")[:11]
        if len(geoid) != 11:
            continue
        s = by_geoid.setdefault(geoid, blank())
        s["claims"] += 1
        s["paid"] += (claim.get("amountPaidOnBuildingClaim") or 0) + (
            claim.get("amountPaidOnContentsClaim") or 0
        )
        if claim.get("yearOfLoss"):
            s["years"].add(claim["yearOfLoss"])
        if claim.get("floodEvent"):
            s["events"][claim["floodEvent"]] = s["events"].get(claim["floodEvent"], 0) + 1

    total = sum(s["claims"] for s in by_geoid.values())  # before any redistribution
    tracts = gpd.read_file(f"zip://{tracts_zip}")
    county_by_fips = {"48061": "Cameron", "48215": "Hidalgo", "48427": "Starr", "48489": "Willacy"}
    tracts = tracts[tracts["GEOID"].str[:5].isin(county_by_fips)].to_crs(4326)
    known = set(tracts["GEOID"])

    stats = {g: s for g, s in by_geoid.items() if g in known}
    old_ids = {g for g in by_geoid if g not in known}
    moved_claims = 0.0
    if old_ids and tracts10_zip.exists():
        old = gpd.read_file(f"zip://{tracts10_zip}")
        old = old[old["GEOID10"].isin(old_ids)][["GEOID10", "geometry"]].to_crs(32614)
        new = tracts[["GEOID", "geometry"]].to_crs(32614)
        pieces = gpd.overlay(old, new, how="intersection", keep_geom_type=True)
        pieces["w"] = pieces.geometry.area
        pieces["w"] = pieces["w"] / pieces.groupby("GEOID10")["w"].transform("sum")
        for row in pieces.itertuples():
            src = by_geoid[row.GEOID10]
            dst = stats.setdefault(row.GEOID, blank())
            dst["claims"] += src["claims"] * row.w
            dst["paid"] += src["paid"] * row.w
            dst["moved"] += src["claims"] * row.w
            dst["years"] |= src["years"]
            for name, n in src["events"].items():
                dst["events"][name] = dst["events"].get(name, 0) + n * row.w
            moved_claims += src["claims"] * row.w
    placed = sum(s["claims"] for s in stats.values())
    print(f"  claims placed on a 2023 tract: {placed:.0f}/{total:.0f} (spread from old tracts: {moved_claims:.0f})")

    counts = sorted(round(s["claims"]) for s in stats.values() if round(s["claims"]))
    breaks = [counts[int(len(counts) * q)] for q in (0.2, 0.4, 0.6, 0.8)] if counts else []

    features = []
    for _, row in tracts.iterrows():
        s = stats.get(row["GEOID"]) or blank()
        n = round(s["claims"])
        cls = 0 if not n else 1 + sum(n > b for b in breaks)
        top_event = max(s["events"], key=s["events"].get) if s["events"] else ""
        feat = _feature(
            row.geometry.__geo_interface__,
            {"overlay_type": "claims", "geoid": row["GEOID"],
             "county": county_by_fips[row["GEOID"][:5]], "claims": n,
             "paid": round(s["paid"]), "claims_class": cls,
             "from_old_tracts": round(s["moved"]),
             "first_year": min(s["years"]) if s["years"] else None,
             "last_year": max(s["years"]) if s["years"] else None, "top_event": top_event},
            tolerance=0.0004,
        )
        if feat:
            features.append(feat)
    return _write_features("nfip-claims-by-tract.geojson", features)


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
        "description": (
            "Just the outlines of the four counties. It sets the area the map "
            "covers and shows no flood risk of its own."
        ),
        "source": "US Census TIGER/Line 2023",
        "vintage": "2023",
        "hazard_type": "n/a — study-area reference",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": "Geographic reference only. Not flood evidence.",
        "source_url": "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    },
    "fema-nfhl": {
        "title": "FEMA effective flood hazard (NFHL)",
        "description": (
            "The official government flood map used to set flood-insurance rates "
            "and building rules. Red areas flood most often, orange areas only in "
            "rarer big storms, and blue areas hardly ever. Not available for "
            "Hidalgo County."
        ),
        "source": "FEMA National Flood Hazard Layer",
        "vintage": "effective FIRM date varies by panel",
        "hazard_type": "effective regulatory flood hazard",
        "coverage": "Cameron, Starr, Willacy",
        "limitation": "No digital NFHL coverage for Hidalgo County. Clipped to county boundary; not a property-level determination.",
        "source_url": "https://msc.fema.gov/portal/home",
    },
    "hidalgo-firm-1981": {
        "title": "Hidalgo County historic flood zones (1981 FIRM)",
        "description": (
            "Hidalgo County's only flood map, drawn back in 1981 — FEMA never "
            "made a modern one here. It's very out of date and leaves out most of "
            "today's neighborhoods, so treat it as a rough guide. Red areas flood "
            "most often, orange less often, blue rarely."
        ),
        "source": "Hidalgo County Drainage District No. 1 — digitized 1981 FIRM",
        "vintage": "1981 base map; some zones later revised by LOMR",
        "hazard_type": "historic local flood-zone reference",
        "coverage": "Hidalgo",
        "limitation": "44 years old; urban core largely undrawn. Legacy B/C zones shown as shaded-X / minimal by long-standing FEMA equivalence, but this is not current effective data.",
        "source_url": "https://www.hcdd1.org/page/floodplains",
    },
    "twdb-cursory-1in100": {
        "title": "TWDB modeled flood extent — 1% annual chance",
        "description": (
            "A state computer model's guess at which land would flood in a bad "
            "storm (about a 1-in-100-year flood), including flooding from heavy "
            "rain. One shaded area, not graded zones. It's an estimate for "
            "context, not an official flood map."
        ),
        "source": "TWDB 2025 cursory floodplain (Fathom 3m)",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
    "twdb-cursory-1in500": {
        "title": "TWDB modeled flood extent — 0.2% annual chance",
        "description": (
            "The same state model, but for a rarer, more extreme flood (about "
            "1-in-500-year) — a wider guess at what could go under water. For "
            "context only, not an official flood map."
        ),
        "source": "TWDB 2025 cursory floodplain (Fathom 3m)",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
    "overture-bridges": {
        "title": "Bridges",
        "description": (
            "Bridges across the four counties — exactly what becomes impassable "
            "when a waterway floods. Not a hazard rating of its own."
        ),
        "source": "Overture Maps Foundation — infrastructure theme (OpenStreetMap)",
        "vintage": "current Overture release",
        "hazard_type": "n/a — infrastructure at risk, not a hazard zone",
        "coverage": "all four counties",
        "limitation": (
            "Crowd-sourced (OpenStreetMap); coverage and names vary by area. "
            "Not an official inventory of flood-prone crossings."
        ),
        "source_url": "https://overturemaps.org/",
    },
    "overture-dams": {
        "title": "Dams",
        "description": (
            "Dams and levees — flood-control infrastructure, relevant to both "
            "flood risk and flood mitigation depending on the structure."
        ),
        "source": "Overture Maps Foundation — infrastructure theme (OpenStreetMap)",
        "vintage": "current Overture release",
        "hazard_type": "n/a — infrastructure, not a hazard zone",
        "coverage": "all four counties",
        "limitation": (
            "Crowd-sourced (OpenStreetMap); coverage and names vary by area. "
            "Not an official inventory."
        ),
        "source_url": "https://overturemaps.org/",
    },
    "hcdd1-flood-extents": {
        "title": "Mapped flooding, 2008–2020 (Hidalgo)",
        "description": (
            "Areas the Hidalgo drainage district mapped as flooded after six past "
            "storms. This is recorded flooding, not a forecast — and it shows where "
            "the old 1981 map misses real flood problems."
        ),
        "source": "Hidalgo County Drainage District No. 1 — Historical Flooding layer",
        "vintage": "events in 2008, 2010, 2015, 2018, 2019, 2020",
        "hazard_type": "observed flooding (district-mapped)",
        "coverage": "Hidalgo, mostly the urban core",
        "limitation": (
            "Only the areas the district mapped, so absence of a shape does not mean "
            "no flooding. The inch range on each event is the district's own label; "
            "whether it is rainfall or flood depth is not stated."
        ),
        "source_url": "https://www.hcdd1.org/",
    },
    "hcdd1-flood-photos": {
        "title": "Flood response photos (Hidalgo)",
        "description": (
            "Locations of field photos the drainage district took while responding "
            "to four floods. Each dot is a place where crews documented conditions."
        ),
        "source": "Hidalgo County Drainage District No. 1 — geotagged flood photos",
        "vintage": "June 2018, Sept 2018, June 2019, Hurricane Hanna 2020",
        "hazard_type": "observed flooding (field documentation)",
        "coverage": "Hidalgo",
        "limitation": (
            "Photos cluster where crews work along drainage assets, and a photo "
            "shows crews were there, not necessarily standing water. Photos are not "
            "reproduced here; GPS tags outside the valley are dropped."
        ),
        "source_url": "https://www.hcdd1.org/",
    },
    "hcdd1-drainage": {
        "title": "Drainage network (Hidalgo)",
        "description": (
            "The drainage district's channels, detention ponds, gates and pumps — "
            "the engineering that decides where stormwater goes."
        ),
        "source": "Hidalgo County Drainage District No. 1 — system, detention and gate/pump layers",
        "vintage": "district records as published",
        "hazard_type": "n/a — drainage infrastructure",
        "coverage": "Hidalgo County Drainage District No. 1 area",
        "limitation": "Reflects what the district publishes; other districts' systems may be missing.",
        "source_url": "https://www.hcdd1.org/",
    },
    "hcdd1-bond-projects": {
        "title": "Drainage improvement projects (Hidalgo)",
        "description": (
            "Projects funded by the district's 2012, 2018 and 2023 bonds — new "
            "drainage built after the 1981 flood map, with each project's status."
        ),
        "source": "Hidalgo County Drainage District No. 1 — bond program layers",
        "vintage": "2012, 2018 and 2023 bond programs",
        "hazard_type": "n/a — infrastructure updates",
        "coverage": "Hidalgo",
        "limitation": "Status is as last published by the district; the 2012 program has no status field.",
        "source_url": "https://www.hcdd1.org/",
    },
    "nfip-claims-by-tract": {
        "title": "Flood insurance claims by tract",
        "description": (
            "How many federal flood-insurance claims were filed in each census tract "
            "since 1978 — a record of where flooding has actually cost people money."
        ),
        "source": "FEMA OpenFEMA — NFIP Redacted Claims v3",
        "vintage": "claims through 2026",
        "hazard_type": "observed flood losses",
        "coverage": "all four counties",
        "limitation": (
            "Counts only insured properties and is not adjusted for how many homes "
            "are insured, so tracts with more policies read higher."
        ),
        "source_url": "https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3",
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
        "overture-bridges": build_overture_infrastructure("bridge", "overture-bridges.geojson"),
        "overture-dams": build_overture_infrastructure("dam", "overture-dams.geojson"),
        "hcdd1-flood-extents": build_hcdd1_flood_extents(),
        "hcdd1-flood-photos": build_hcdd1_flood_photos(),
        "hcdd1-drainage": build_hcdd1_drainage(),
        "hcdd1-bond-projects": build_hcdd1_bond_projects(),
        "nfip-claims-by-tract": build_nfip_claims_by_tract(),
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
