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

Run:  uv run --group pipeline python scripts/fetch_ml_inputs.py [--only a,b] [--force]
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "ml" / "raw"
UA = {"User-Agent": "RGV-Flood-Impact-Visualizer/1.0 (student research)"}

# Union of the four counties, padded a little. West, south, east, north.
AREA = (-99.25, 25.80, -97.00, 26.85)

COUNTY_FIPS = {"cameron": "48061", "hidalgo": "48215", "starr": "48427", "willacy": "48489"}

FORCE = False


def log(msg: str) -> None:
    print(msg, flush=True)


def http_json(url: str, timeout: int = 90) -> dict | list:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def download(url: str, dest: Path, timeout: int = 300) -> bool:
    if dest.exists() and dest.stat().st_size > 0 and not FORCE:
        log(f"  skip (exists) {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, part.open("wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log(f"  FAILED {dest.name}: {error}")
        part.unlink(missing_ok=True)
        return False
    part.replace(dest)
    log(f"  ok {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return True


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


def fetch_arcgis_layer(service: str, layer: int, dest: Path) -> int:
    base = f"{HCDD1_BASE}/{service}/FeatureServer/{layer}/query"
    features: list[dict] = []
    offset, page = 0, 1000
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page,
        }
        data = http_json(f"{base}?{urllib.parse.urlencode(params)}", timeout=120)
        batch = data.get("features", [])
        if not batch:
            break
        features.extend(batch)
        offset += len(batch)
    dest.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    return len(features)


def step_hcdd1() -> None:
    out = RAW / "hcdd1"
    out.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for service, layer, name in HCDD1_LAYERS:
        dest = out / f"{name}.geojson"
        if dest.exists() and dest.stat().st_size > 0 and not FORCE:
            log(f"  skip (exists) {dest.name}")
            continue
        try:
            n = fetch_arcgis_layer(service, layer, dest)
            inventory[name] = {"service": service, "layer": layer, "features": n}
            log(f"  ok {name}: {n} features")
        except Exception as error:  # noqa: BLE001 -- keep going, report at the end
            log(f"  FAILED {name} ({service}/{layer}): {error}")
    if inventory:
        (out / "_inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")


# ---- NFIP / FEMA -----------------------------------------------------------


def http_json_retry(url: str, attempts: int = 8) -> dict | list:
    """OpenFEMA 503s under load; back off and retry rather than lose the run."""
    for attempt in range(attempts):
        try:
            return http_json(url, timeout=180)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as error:
            wait = min(10 * 2**attempt, 120)
            log(f"    retry {attempt + 1}/{attempts} after {error!r}; waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"gave up on {url[:120]}")


def paged_openfema(
    dataset: str, version: str, filter_expr: str, dest: Path, select: str = "", page: int = 10000
) -> int:
    """Stream a filtered dataset to NDJSON. Written to .part and renamed only on
    completion, so an interrupted run can never leave a truncated file that later
    looks finished. $orderby=id keeps $skip paging stable."""
    base = f"https://www.fema.gov/api/open/{version}/{dataset}"
    part = dest.with_suffix(dest.suffix + ".part")
    skip = total = 0
    with part.open("w", encoding="utf-8") as out:
        while True:
            params = {"$filter": filter_expr, "$top": page, "$skip": skip, "$orderby": "id"}
            if select:
                params["$select"] = select
            data = http_json_retry(f"{base}?{urllib.parse.urlencode(params)}")
            rows = data.get(dataset, [])
            if not rows:
                break
            for row in rows:
                out.write(json.dumps(row) + "\n")
            total += len(rows)
            skip += len(rows)
            log(f"    {dataset}: {total} rows")
            if len(rows) < page:
                break
    part.replace(dest)
    return total


def step_nfip() -> None:
    out = RAW / "nfip"
    out.mkdir(parents=True, exist_ok=True)
    codes = " or ".join(f"countyCode eq '{c}'" for c in COUNTY_FIPS.values())

    claims = out / "nfip_claims_v3.ndjson"
    if claims.exists() and claims.stat().st_size > 0 and not FORCE:
        log(f"  skip (exists) {claims.name}")
    else:
        n = paged_openfema("NfipClaims", "v3", f"({codes})", claims)
        log(f"  ok claims: {n}")

    decl = out / "disaster_declarations.json"
    if not decl.exists() or FORCE:
        rows = []
        for code in COUNTY_FIPS.values():
            f = f"fipsStateCode eq '48' and fipsCountyCode eq '{code[2:]}'"
            url = (
                "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?"
                + urllib.parse.urlencode({"$filter": f, "$top": 1000})
            )
            rows.extend(http_json(url).get("DisasterDeclarationsSummaries", []))
        decl.write_text(json.dumps(rows), encoding="utf-8")
        log(f"  ok disaster declarations: {len(rows)}")


def step_nfip_policies() -> None:
    """NFIP policies (denominators for claims-per-policy). Separate from claims
    because it is ~450k rows from a flaky API and the v2 source disappears on
    2026-10-15."""
    out = RAW / "nfip"
    out.mkdir(parents=True, exist_ok=True)
    codes = " or ".join(f"countyCode eq '{c}'" for c in COUNTY_FIPS.values())
    policies = out / "nfip_policies_v2.ndjson"
    if policies.exists() and policies.stat().st_size > 0 and not FORCE:
        log(f"  skip (exists) {policies.name}")
    else:
        # v3 policies have no county field and time out on any server-side
        # filter (503), so policies come from the v2 dataset instead. v2 is frozen
        # (data as of 2026-06-01) and OpenFEMA removes it on 2026-10-15 -- this is
        # the last chance to fetch it, so the downloaded file is the keeper.
        sample = http_json_retry(
            "https://www.fema.gov/api/open/v2/FimaNfipPolicies?$top=1&$filter="
            + urllib.parse.quote("countyCode eq '48215'")
        )["FimaNfipPolicies"][0]
        want = [
            "countyCode", "censusTract", "censusBlockGroupFips", "floodZoneCurrent",
            "ratedFloodZone", "latitude", "longitude", "policyCount", "policyEffectiveDate",
            "policyTerminationDate", "originalConstructionDate", "originalNBDate",
            "elevatedBuildingIndicator", "baseFloodElevation", "lowestFloorElevation",
            "totalBuildingInsuranceCoverage", "buildingReplacementCost", "occupancyType",
            "postFIRMConstructionIndicator", "reportedZipCode", "nfipCommunityName",
        ]
        select = ",".join(k for k in want if k in sample)
        log(f"  policies: selecting {len(select.split(','))} fields")
        n = paged_openfema(
            "FimaNfipPolicies", "v2", f"({codes})", policies, select=select, page=5000
        )
        log(f"  ok policies: {n}")


# ---- Census tracts ---------------------------------------------------------


def step_tracts() -> None:
    out = RAW / "tracts"
    download("https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_48_tract.zip",
             out / "tl_2023_48_tract.zip")
    download("https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_48_tract10.zip",
             out / "tl_2010_48_tract10.zip")


# ---- NLCD ------------------------------------------------------------------

NLCD_WCS = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
NLCD_COVERAGES = (
    [(y, "Impervious") for y in (2001, 2006, 2011, 2016, 2021)]
    + [(y, "Land_Cover") for y in (2001, 2011, 2021)]
)


def step_nlcd() -> None:
    out = RAW / "nlcd"
    west, south, east, north = AREA
    for year, kind in NLCD_COVERAGES:
        params = {
            "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
            "coverageId": f"mrlc_download__NLCD_{year}_{kind}_L48",
            "format": "image/geotiff",
            "subsettingCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
        }
        url = (
            f"{NLCD_WCS}?{urllib.parse.urlencode(params)}"
            f"&subset=Lat({south},{north})&subset=Long({west},{east})"
        )
        download(url, out / f"NLCD_{year}_{kind}.tif")


# ---- NOAA Atlas 14 ---------------------------------------------------------


def step_atlas14() -> None:
    out = RAW / "atlas14"
    aris = (1, 2, 5, 10, 25, 50, 100, 200, 500, 1000)
    for dur in ("60ma", "06ha", "24ha"):
        for ari in aris:
            name = f"tx{ari}yr{dur}.zip"
            download(f"https://hdsc.nws.noaa.gov/pub/hdsc/data/tx/{name}", out / name)


# ---- 3DEP elevation --------------------------------------------------------


def step_dem() -> None:
    out = RAW / "dem"
    west, south, east, north = AREA
    params = {
        "datasets": "National Elevation Dataset (NED) 1/3 arc-second",
        "bbox": f"{west},{south},{east},{north}",
        "max": 100,
        "outputFormat": "JSON",
    }
    items = http_json(
        "https://tnmaccess.nationalmap.gov/api/v1/products?" + urllib.parse.urlencode(params)
    ).get("items", [])
    newest: dict[str, dict] = {}
    for item in items:
        match = re.search(r"n\d+w\d+", item.get("title", ""))
        url = item.get("downloadURL", "")
        if not match or not url.lower().endswith(".tif"):
            continue
        key = match.group(0)
        if key not in newest or item.get("publicationDate", "") > newest[key].get("publicationDate", ""):
            newest[key] = item
    log(f"  {len(newest)} tile(s): {', '.join(sorted(newest))}")
    for key, item in sorted(newest.items()):
        download(item["downloadURL"], out / f"{key}_{item['downloadURL'].rsplit('/', 1)[-1]}")


# ---- Overture --------------------------------------------------------------

OVERTURE_TYPES = ["building", "segment", "water", "land_use", "land_cover", "place", "infrastructure"]


def step_overture() -> None:
    from overturemaps.core import record_batch_reader
    from overturemaps.writers import copy, get_writer

    out = RAW / "overture"
    out.mkdir(parents=True, exist_ok=True)
    for kind in OVERTURE_TYPES:
        dest = out / f"{kind}.parquet"
        if dest.exists() and dest.stat().st_size > 0 and not FORCE:
            log(f"  skip (exists) {dest.name}")
            continue
        log(f"  downloading Overture {kind} ...")
        reader = record_batch_reader(kind, bbox=AREA, stac=True)
        if reader is None:
            log(f"  FAILED {kind}: no reader")
            continue
        part = dest.with_suffix(".parquet.part")
        writer = get_writer("geoparquet", str(part), reader.schema)
        try:
            copy(reader, writer)
        finally:
            writer.close()
        part.replace(dest)
        log(f"  ok {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")


# ---- SSURGO soils ----------------------------------------------------------

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest"
SOIL_ATTRS = ("hydgrpdcd", "drclassdcd", "wtdepannmin", "brockdepmin", "slopegraddcp")


def sda_query(sql: str) -> list[list]:
    body = json.dumps({"query": sql, "format": "JSON+COLUMNNAME"}).encode()
    req = urllib.request.Request(
        SDA_URL, data=body, headers={**UA, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp).get("Table", [])[1:]  # drop the column-name row


def step_soils() -> None:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping

    dest = RAW / "soils" / "ssurgo_mapunits.geojson"
    if dest.exists() and dest.stat().st_size > 0 and not FORCE:
        log(f"  skip (exists) {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)

    west, south, east, north = AREA
    step = 0.2
    polygons: dict[str, tuple[str, str]] = {}  # mupolygonkey -> (mukey, wkt)
    y = south
    while y < north:
        x = west
        while x < east:
            ring = (
                f"POLYGON(({x} {y},{x + step} {y},{x + step} {y + step},"
                f"{x} {y + step},{x} {y}))"
            )
            sql = (
                "SELECT mukey, mupolygonkey, mupolygongeo.STAsText() FROM mupolygon "
                f"WHERE mupolygongeo.STIntersects(geometry::STGeomFromText('{ring}',4326))=1"
            )
            try:
                for mukey, polykey, geom in sda_query(sql):
                    polygons[polykey] = (mukey, geom)
            except Exception as error:  # noqa: BLE001 -- report the gap, keep going
                log(f"  tile ({x:.2f},{y:.2f}) FAILED: {error}")
            x += step
        y += step
        log(f"  soils: {len(polygons)} polygons through lat {y:.2f}")

    mukeys = sorted({mukey for mukey, _ in polygons.values()})
    attrs: dict[str, dict] = {}
    for i in range(0, len(mukeys), 300):
        chunk = ",".join(mukeys[i : i + 300])
        sql = f"SELECT mukey, {', '.join(SOIL_ATTRS)} FROM muaggatt WHERE mukey IN ({chunk})"
        for row in sda_query(sql):
            attrs[row[0]] = dict(zip(SOIL_ATTRS, row[1:], strict=True))

    features = [
        {
            "type": "Feature",
            "geometry": mapping(shapely_wkt.loads(geom)),
            "properties": {"mukey": mukey, "mupolygonkey": polykey, **attrs.get(mukey, {})},
        }
        for polykey, (mukey, geom) in polygons.items()
    ]
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    log(f"  ok soils: {len(features)} polygons, {len(mukeys)} map units ({dest.stat().st_size / 1e6:.0f} MB)")


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
    global FORCE
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", help=f"comma-separated subset of: {', '.join(STEPS)}")
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()
    FORCE = args.force

    chosen = args.only.split(",") if args.only else list(STEPS)
    unknown = [s for s in chosen if s not in STEPS]
    if unknown:
        sys.exit(f"unknown step(s): {', '.join(unknown)}")

    failures = []
    for name in chosen:
        log(f"\n== {name} ==")
        started = time.time()
        try:
            STEPS[name]()
        except Exception as error:  # noqa: BLE001 -- one source failing shouldn't stop the rest
            log(f"  STEP FAILED: {error!r}")
            failures.append(name)
        log(f"  ({time.time() - started:.0f}s)")
    log("\nDone." + (f" Failed steps: {', '.join(failures)}" if failures else " All steps ok."))


if __name__ == "__main__":
    main()
