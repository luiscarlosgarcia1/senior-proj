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
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

from jsonio import feature_collection, write_json
from net import NETWORK_ERRORS, already_have, download, get_json
from paths import ML_RAW as RAW

from rgv_flood.counties import COUNTIES

# West, south, east, north: the four counties padded only a little. Tighter than
# counties.RGV_BBOX on purpose, because every degree here is downloaded.
AREA = (-99.25, 25.80, -97.00, 26.85)

COUNTY_FIPS = {slug: county["fips"] for slug, county in COUNTIES.items()}


# ---- HCDD1 -----------------------------------------------------------------

HCDD1_BASE = "https://services7.arcgis.com/JSUhwVSJhyVkcN3Q/arcgis/rest/services"

# (service, layer id, output name). Skipped on purpose: parcels, survey123
# forms, and the 41,859-segment road centerline layer (Overture covers roads).
HCDD1_LAYERS = [
    ("Historical_Flooding_Layer", 0, "flood_photos_2020_hanna"),
    ("Historical_Flooding_Layer", 1, "flood_photos_2019_june"),
    ("Historical_Flooding_Layer", 2, "flood_photos_2018_sept"),
    ("Historical_Flooding_Layer", 3, "flood_photos_2018_june"),
    ("Historical_Flooding_Layer", 4, "flood_extent_2020_8to14in"),
    ("Historical_Flooding_Layer", 5, "flood_extent_2019_4to10in"),
    ("Historical_Flooding_Layer", 6, "flood_extent_2018_4to18in"),
    ("Historical_Flooding_Layer", 7, "flood_extent_2015_1to8in"),
    ("Historical_Flooding_Layer", 8, "flood_extent_2010_3to6in"),
    ("Historical_Flooding_Layer", 9, "flood_extent_2008_4to10in"),
    ("Hanna_Geotagged_Photos", 0, "hanna_geotagged_photos"),
    ("Precinct_4_Calls", 0, "precinct4_calls"),
    ("Detention_Ponds", 0, "detention_ponds"),
    ("DetentionPonds", 0, "detention_ponds_alt"),
    ("HCDD1_System", 0, "drainage_system"),
    ("Ditch_Maintenance", 0, "ditch_maintenance"),
    ("Future_System", 0, "future_system"),
    ("Gates_Pumps", 0, "gates_pumps"),
    ("Gate_Pumps_New", 0, "gates_pumps_new"),
    ("Precinct_4_Valves_Gates", 0, "precinct4_valves_gates"),
    ("PumpFlowterInstall", 0, "pump_flowter_install"),
    ("Map", 0, "ditches_weslaco"),
    ("Map", 1, "ditches_edinburg"),
    ("Map", 2, "ditches_mcallen"),
    ("Map", 3, "ditches_mission"),
    ("Map", 4, "ditches_pharr"),
    ("ArcGIS_Online_Two", 0, "arcgis_online_two"),
    ("2012_Bond_Program", 0, "bond_2012"),
    ("2018_Bond_Program", 0, "bond_2018"),
    ("2023_Bond", 0, "bond_2023"),
    ("District_Projects", 2, "district_projects"),
    ("Projects_Merged0119", 0, "projects_merged_0119"),
    ("Subd_Dev_Note", 0, "subdivision_dev_notes"),
    ("LOMR_CLOMR", 0, "lomr_clomr"),
    ("FEMA_Hidalgo_FIRM", 0, "fema_hidalgo_firm"),
    ("HCDD1_HMAP", 0, "hazard_mitigation_areas"),
    ("HCDD1_Boundary", 0, "hcdd1_boundary"),
    ("HCDD1_Discharge_Permits", 0, "discharge_permits"),
    ("Irrigation_Dist_Boundaries", 1, "irrigation_offices"),
    ("Irrigation_Dist_Boundaries", 2, "irrigation_districts"),
    ("City_Limits_2020", 0, "city_limits_2020"),
    ("Rain_n_Stream_Gauges", 1, "gauges_rain"),
    ("Rain_n_Stream_Gauges", 3, "gauges_stream"),
    ("Rain_n_Stream_Gauges", 4, "gauges_rain_stream"),
]


def fetch_arcgis_layer(service: str, layer: int) -> list[dict]:
    """Every feature of one ArcGIS layer as GeoJSON, paged because servers cap
    how many features one response may carry."""
    base = f"{HCDD1_BASE}/{service}/FeatureServer/{layer}/query"
    features: list[dict] = []
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": len(features),
            "resultRecordCount": 1000,
        }
        page = get_json(f"{base}?{urllib.parse.urlencode(params)}", timeout=120)["features"]
        if not page:
            return features
        features += page


def step_hcdd1(force: bool) -> None:
    out = RAW / "hcdd1"
    out.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for service, layer, name in HCDD1_LAYERS:
        dest = out / f"{name}.geojson"
        if already_have(dest, force=force):
            continue
        try:
            features = fetch_arcgis_layer(service, layer)
        except (*NETWORK_ERRORS, ValueError, KeyError) as error:  # one layer failing shouldn't lose the rest
            print(f"  [fail] {name} ({service}/{layer}): {error}")
            continue
        dest.write_text(json.dumps(feature_collection(features)), encoding="utf-8")
        inventory[name] = {"service": service, "layer": layer, "features": len(features)}
        print(f"  [ok]   {name}: {len(features)} features")
    if inventory:
        write_json(out / "_inventory.json", inventory)


# ---- NFIP / FEMA -----------------------------------------------------------

OPENFEMA = "https://www.fema.gov/api/open"

# Policy fields worth keeping; the API returns ~60 per row.
POLICY_FIELDS = (
    "countyCode,censusTract,censusBlockGroupFips,floodZoneCurrent,ratedFloodZone,latitude,longitude,"
    "policyCount,policyEffectiveDate,policyTerminationDate,originalConstructionDate,originalNBDate,"
    "elevatedBuildingIndicator,baseFloodElevation,lowestFloorElevation,totalBuildingInsuranceCoverage,"
    "buildingReplacementCost,occupancyType,postFIRMConstructionIndicator,reportedZipCode,nfipCommunityName"
)


def export_openfema(dataset: str, version: str, dest: Path, *, select: str = "") -> int:
    """The four counties' rows of an OpenFEMA dataset as NDJSON, via its file-export
    endpoint.

    Without `$top` the `.jsonl` endpoint streams every matching row in one response,
    so there is no paging (deep `$skip` queries time out on the big tables). Each
    county is its own request, kept in a parts folder so an interrupted run resumes
    where it stopped instead of starting over.
    """
    parts = dest.parent / f".{dest.stem}-parts"
    for slug, fips in COUNTY_FIPS.items():
        params = {"$filter": f"countyCode eq '{fips}'"}
        if select:
            params["$select"] = select
        url = f"{OPENFEMA}/{version}/{dataset}.jsonl?{urllib.parse.urlencode(params)}"
        download(url, parts / f"{slug}.ndjson", attempts=6)

    rows = 0
    part = dest.with_suffix(dest.suffix + ".part")
    with part.open("wb") as out:
        for piece in sorted(parts.glob("*.ndjson")):
            data = piece.read_bytes().rstrip(b"\n") + b"\n"  # the export has no trailing newline
            out.write(data)
            rows += data.count(b"\n")
    part.replace(dest)
    shutil.rmtree(parts)
    return rows


def step_nfip(force: bool) -> None:
    out = RAW / "nfip"
    out.mkdir(parents=True, exist_ok=True)

    claims = out / "nfip_claims_v3.ndjson"
    if not already_have(claims, force=force):
        print(f"  [ok]   claims: {export_openfema('NfipClaims', 'v3', claims)}")

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
    out = RAW / "tracts"
    download("https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_48_tract.zip",
             out / "tl_2023_48_tract.zip", force=force)
    download("https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_48_tract10.zip",
             out / "tl_2010_48_tract10.zip", force=force)


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
