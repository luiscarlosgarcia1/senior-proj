#!/usr/bin/env python3
"""Gather every public input for the Hidalgo flood-susceptibility ML work.

Plan: learn how terrain/drainage/land cover relate to FEMA flood zones in the
three counties that have a modern NFHL (Cameron, Starr, Willacy), predict
Hidalgo (whose only map is the 1981 FIRM), and calibrate against Hidalgo's own
flood evidence. This script only *gathers*; nothing here trains or predicts.

Everything lands under data/ml/raw/<source>/ (gitignored: all of it is public
and re-downloadable). Re-runs skip files that already exist; --force redoes them.

Sources
  hcdd1     Hidalgo County Drainage District No. 1 ArcGIS: flood photos/extents
            (2008-2020 events), detention ponds, ditches, gates/pumps, bond
            projects (infrastructure updates), LOMR, gauges
  nfip      OpenFEMA NFIP claims (v3) and disaster declarations
  nfip_policies  NFIP policies (v2 -- removed by FEMA 2026-10-15; slow, run on its own)
  tracts    Census tracts (2010 and 2023 vintages -- claims span both)
  nlcd      NLCD impervious surface + land cover, several years, clipped to the RGV
  atlas14   NOAA Atlas 14 Vol. 11 rainfall-frequency grids
  soils     USDA SSURGO map-unit polygons + hydrologic group / drainage class
  dem       USGS 3DEP 1/3 arc-second elevation tiles
  overture  Overture buildings, roads, water, land use/cover, places, infrastructure

Run:  uv run --group pipeline python pipeline/fetch_ml_inputs.py [--only a,b] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse

from jsonio import feature_collection, write_json
from net import NETWORK_ERRORS, already_have, download, get_json
from paths import ML_RAW as RAW
from public_sources import (
    HCDD1_LAYERS,
    OPENFEMA,
    census_tracts,
    export_openfema,
    hcdd1_layer,
    nfip_claims,
)

from rgv_flood.counties import COUNTIES

# West, south, east, north: the four counties padded only a little. Tighter than
# counties.RGV_BBOX on purpose, because every degree here is downloaded.
AREA = (-99.25, 25.80, -97.00, 26.85)

COUNTY_FIPS = {slug: county["fips"] for slug, county in COUNTIES.items()}


# ---- HCDD1 -----------------------------------------------------------------


def step_hcdd1(force: bool) -> None:
    inventory = {}
    for name, (service, layer) in HCDD1_LAYERS.items():
        try:
            features = hcdd1_layer(name, RAW / "hcdd1", force=force)
        except (*NETWORK_ERRORS, ValueError, KeyError) as error:  # one layer failing shouldn't lose the rest
            print(f"  [fail] {name} ({service}/{layer}): {error}")
            continue
        inventory[name] = {"service": service, "layer": layer, "features": len(features)}
    write_json(RAW / "hcdd1" / "_inventory.json", inventory)


# ---- NFIP / FEMA -----------------------------------------------------------

# Policy fields worth keeping; the API returns ~60 per row.
POLICY_FIELDS = (
    "countyCode,censusTract,censusBlockGroupFips,floodZoneCurrent,ratedFloodZone,latitude,longitude,"
    "policyCount,policyEffectiveDate,policyTerminationDate,originalConstructionDate,originalNBDate,"
    "elevatedBuildingIndicator,baseFloodElevation,lowestFloorElevation,totalBuildingInsuranceCoverage,"
    "buildingReplacementCost,occupancyType,postFIRMConstructionIndicator,reportedZipCode,nfipCommunityName"
)


def step_nfip(force: bool) -> None:
    out = RAW / "nfip"
    nfip_claims(out, force=force)

    declarations = out / "disaster_declarations.json"
    if not already_have(declarations, force=force):
        rows = []
        for fips in COUNTY_FIPS.values():
            params = {"$filter": f"fipsStateCode eq '48' and fipsCountyCode eq '{fips[2:]}'", "$top": 1000}
            url = f"{OPENFEMA}/v2/DisasterDeclarationsSummaries?{urllib.parse.urlencode(params)}"
            rows += get_json(url, attempts=4)["DisasterDeclarationsSummaries"]
        declarations.write_text(json.dumps(rows), encoding="utf-8")
        print(f"  [ok]   disaster declarations: {len(rows)}")


def step_nfip_policies(force: bool) -> None:
    """NFIP policies, the denominators for claims-per-policy. Separate from claims
    because it is ~450k rows from a flaky API.

    v3 policies have no county field and time out on any server-side filter, so
    these come from the v2 dataset. v2 is frozen (data as of 2026-06-01) and
    OpenFEMA removes it on 2026-10-15, so the downloaded file is the keeper.
    """
    out = RAW / "nfip"
    out.mkdir(parents=True, exist_ok=True)
    policies = out / "nfip_policies_v2.ndjson"
    if not already_have(policies, force=force):
        print(f"  [ok]   policies: {export_openfema('FimaNfipPolicies', 'v2', policies, select=POLICY_FIELDS)}")


# ---- Census tracts ---------------------------------------------------------


def step_tracts(force: bool) -> None:
    for vintage in (2023, 2010):
        census_tracts(vintage, RAW / "tracts", force=force)


# ---- NLCD ------------------------------------------------------------------

NLCD_WCS = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
NLCD_COVERAGES = [(y, "Impervious") for y in (2001, 2006, 2011, 2016, 2021)] + [
    (y, "Land_Cover") for y in (2001, 2011, 2021)
]


def step_nlcd(force: bool) -> None:
    west, south, east, north = AREA
    for year, kind in NLCD_COVERAGES:
        params = {
            "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
            "coverageId": f"mrlc_download__NLCD_{year}_{kind}_L48",
            "format": "image/geotiff",
            "subsettingCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
        }
        url = f"{NLCD_WCS}?{urllib.parse.urlencode(params)}&subset=Lat({south},{north})&subset=Long({west},{east})"
        download(url, RAW / "nlcd" / f"NLCD_{year}_{kind}.tif", required=False, force=force)


# ---- NOAA Atlas 14 ---------------------------------------------------------


def step_atlas14(force: bool) -> None:
    return_periods = (1, 2, 5, 10, 25, 50, 100, 200, 500, 1000)
    for duration in ("60ma", "06ha", "24ha"):  # 60 minutes, 6 hours, 24 hours
        for years in return_periods:
            name = f"tx{years}yr{duration}.zip"
            download(f"https://hdsc.nws.noaa.gov/pub/hdsc/data/tx/{name}", RAW / "atlas14" / name,
                     required=False, force=force)


# ---- 3DEP elevation --------------------------------------------------------


def step_dem(force: bool) -> None:
    west, south, east, north = AREA
    params = {
        "datasets": "National Elevation Dataset (NED) 1/3 arc-second",
        "bbox": f"{west},{south},{east},{north}",
        "max": 100,
        "outputFormat": "JSON",
    }
    items = get_json("https://tnmaccess.nationalmap.gov/api/v1/products?" + urllib.parse.urlencode(params))["items"]

    newest: dict[str, dict] = {}  # tile name (n26w098) -> its most recently published file
    for item in items:
        tile = re.search(r"n\d+w\d+", item.get("title", ""))
        if tile and item.get("downloadURL", "").lower().endswith(".tif"):
            current = newest.get(tile.group(0))
            if current is None or item.get("publicationDate", "") > current.get("publicationDate", ""):
                newest[tile.group(0)] = item
    print(f"  {len(newest)} tile(s): {', '.join(sorted(newest))}")
    for tile, item in sorted(newest.items()):
        url = item["downloadURL"]
        download(url, RAW / "dem" / f"{tile}_{url.rsplit('/', 1)[-1]}", required=False, force=force)


# ---- Overture --------------------------------------------------------------

OVERTURE_TYPES = ["building", "segment", "water", "land_use", "land_cover", "place", "infrastructure"]


def step_overture(force: bool) -> None:
    from overturemaps.core import record_batch_reader
    from overturemaps.writers import copy, get_writer

    out = RAW / "overture"
    out.mkdir(parents=True, exist_ok=True)
    for kind in OVERTURE_TYPES:
        dest = out / f"{kind}.parquet"
        if already_have(dest, force=force):
            continue
        print(f"  downloading Overture {kind} ...")
        reader = record_batch_reader(kind, bbox=AREA, stac=True)
        if reader is None:
            print(f"  [fail] {kind}: no data returned")
            continue
        part = dest.with_suffix(".parquet.part")
        writer = get_writer("geoparquet", str(part), reader.schema)
        try:
            copy(reader, writer)
        finally:
            writer.close()
        part.replace(dest)
        print(f"  [ok]   {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")


# ---- SSURGO soils ----------------------------------------------------------

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest"
SOIL_ATTRS = ("hydgrpdcd", "drclassdcd", "wtdepannmin", "brockdepmin", "slopegraddcp")
SOIL_TILE_DEGREES = 0.2  # query the soil service in small tiles; big ones time out


def sda_query(sql: str) -> list[list]:
    """Rows from USDA's Soil Data Access SQL endpoint (the column-name row dropped)."""
    response = get_json(SDA_URL, body={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=300)
    return response.get("Table", [])[1:]


def _soil_polygons() -> dict[str, tuple[str, str]]:
    """mupolygonkey -> (mukey, WKT) for every soil map-unit polygon in AREA."""
    west, south, east, north = AREA
    polygons: dict[str, tuple[str, str]] = {}
    y = south
    while y < north:
        x = west
        while x < east:
            x2, y2 = x + SOIL_TILE_DEGREES, y + SOIL_TILE_DEGREES
            ring = f"POLYGON(({x} {y},{x2} {y},{x2} {y2},{x} {y2},{x} {y}))"
            sql = (
                "SELECT mukey, mupolygonkey, mupolygongeo.STAsText() FROM mupolygon "
                f"WHERE mupolygongeo.STIntersects(geometry::STGeomFromText('{ring}',4326))=1"
            )
            try:
                for mukey, polygon_key, wkt in sda_query(sql):
                    polygons[polygon_key] = (mukey, wkt)
            except (*NETWORK_ERRORS, ValueError, KeyError) as error:  # report the gap and keep going
                print(f"  [fail] tile ({x:.2f},{y:.2f}): {error}")
            x = x2
        y += SOIL_TILE_DEGREES
        print(f"  soils: {len(polygons)} polygons through lat {y:.2f}", flush=True)
    return polygons


def step_soils(force: bool) -> None:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping

    dest = RAW / "soils" / "ssurgo_mapunits.geojson"
    if already_have(dest, force=force):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)

    polygons = _soil_polygons()
    mukeys = sorted({mukey for mukey, _ in polygons.values()})
    attributes: dict[str, dict] = {}
    for start in range(0, len(mukeys), 300):
        chunk = ",".join(mukeys[start : start + 300])
        for mukey, *values in sda_query(f"SELECT mukey, {', '.join(SOIL_ATTRS)} FROM muaggatt WHERE mukey IN ({chunk})"):
            attributes[mukey] = dict(zip(SOIL_ATTRS, values, strict=True))

    features = [
        {
            "type": "Feature",
            "geometry": mapping(shapely_wkt.loads(wkt)),
            "properties": {"mukey": mukey, "mupolygonkey": polygon_key, **attributes.get(mukey, {})},
        }
        for polygon_key, (mukey, wkt) in polygons.items()
    ]
    dest.write_text(json.dumps(feature_collection(features)), encoding="utf-8")
    print(f"  [ok]   soils: {len(features)} polygons, {len(mukeys)} map units ({dest.stat().st_size / 1e6:.0f} MB)")


STEPS = {
    "hcdd1": step_hcdd1,
    "nfip": step_nfip,
    "nfip_policies": step_nfip_policies,
    "tracts": step_tracts,
    "nlcd": step_nlcd,
    "atlas14": step_atlas14,
    "soils": step_soils,
    "dem": step_dem,
    "overture": step_overture,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", help=f"comma-separated subset of: {', '.join(STEPS)}")
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()

    chosen = args.only.split(",") if args.only else list(STEPS)
    unknown = [name for name in chosen if name not in STEPS]
    if unknown:
        sys.exit(f"unknown step(s): {', '.join(unknown)}")

    failed = []
    for name in chosen:
        print(f"\n== {name} ==", flush=True)
        started = time.time()
        try:
            STEPS[name](args.force)
        except Exception as error:  # noqa: BLE001 - one source failing shouldn't stop the rest
            print(f"  STEP FAILED: {error!r}")
            failed.append(name)
        print(f"  ({time.time() - started:.0f}s)")
    print("\nDone." + (f" Failed steps: {', '.join(failed)}" if failed else " All steps ok."))


if __name__ == "__main__":
    main()
