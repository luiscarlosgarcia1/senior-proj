"""Public datasets that more than one script downloads: the Hidalgo drainage
district's ArcGIS layers, FEMA's NFIP claims, and Census tracts.

Each function returns data that is downloaded once and kept in a cache folder
exactly as the publisher sent it. The map build (`evidence_layers.py`) uses the
default cache under `tmp/`; `fetch_ml_inputs.py` passes its own folder.
"""

from __future__ import annotations

import json
import shutil
import urllib.parse
from pathlib import Path

from jsonio import feature_collection
from net import already_have, download, get_json
from paths import DOWNLOAD_CACHE

from rgv_flood.counties import COUNTIES

# ---- Hidalgo County Drainage District No. 1 ---------------------------------

HCDD1_BASE = "https://services7.arcgis.com/JSUhwVSJhyVkcN3Q/arcgis/rest/services"

# Our name for a layer -> (ArcGIS service, layer id). Skipped on purpose:
# parcels, survey123 forms, and the 41,859-segment road centerline layer.
HCDD1_LAYERS = {
    "flood_photos_2020_hanna": ("Historical_Flooding_Layer", 0),
    "flood_photos_2019_june": ("Historical_Flooding_Layer", 1),
    "flood_photos_2018_sept": ("Historical_Flooding_Layer", 2),
    "flood_photos_2018_june": ("Historical_Flooding_Layer", 3),
    "flood_extent_2020_8to14in": ("Historical_Flooding_Layer", 4),
    "flood_extent_2019_4to10in": ("Historical_Flooding_Layer", 5),
    "flood_extent_2018_4to18in": ("Historical_Flooding_Layer", 6),
    "flood_extent_2015_1to8in": ("Historical_Flooding_Layer", 7),
    "flood_extent_2010_3to6in": ("Historical_Flooding_Layer", 8),
    "flood_extent_2008_4to10in": ("Historical_Flooding_Layer", 9),
    "hanna_geotagged_photos": ("Hanna_Geotagged_Photos", 0),
    "precinct4_calls": ("Precinct_4_Calls", 0),
    "detention_ponds": ("Detention_Ponds", 0),
    "detention_ponds_alt": ("DetentionPonds", 0),
    "drainage_system": ("HCDD1_System", 0),
    "ditch_maintenance": ("Ditch_Maintenance", 0),
    "future_system": ("Future_System", 0),
    "gates_pumps": ("Gates_Pumps", 0),
    "gates_pumps_new": ("Gate_Pumps_New", 0),
    "precinct4_valves_gates": ("Precinct_4_Valves_Gates", 0),
    "pump_flowter_install": ("PumpFlowterInstall", 0),
    "ditches_weslaco": ("Map", 0),
    "ditches_edinburg": ("Map", 1),
    "ditches_mcallen": ("Map", 2),
    "ditches_mission": ("Map", 3),
    "ditches_pharr": ("Map", 4),
    "arcgis_online_two": ("ArcGIS_Online_Two", 0),
    "bond_2012": ("2012_Bond_Program", 0),
    "bond_2018": ("2018_Bond_Program", 0),
    "bond_2023": ("2023_Bond", 0),
    "district_projects": ("District_Projects", 2),
    "projects_merged_0119": ("Projects_Merged0119", 0),
    "subdivision_dev_notes": ("Subd_Dev_Note", 0),
    "lomr_clomr": ("LOMR_CLOMR", 0),
    "fema_hidalgo_firm": ("FEMA_Hidalgo_FIRM", 0),
    "hazard_mitigation_areas": ("HCDD1_HMAP", 0),
    "hcdd1_boundary": ("HCDD1_Boundary", 0),
    "discharge_permits": ("HCDD1_Discharge_Permits", 0),
    "irrigation_offices": ("Irrigation_Dist_Boundaries", 1),
    "irrigation_districts": ("Irrigation_Dist_Boundaries", 2),
    "city_limits_2020": ("City_Limits_2020", 0),
    "gauges_rain": ("Rain_n_Stream_Gauges", 1),
    "gauges_stream": ("Rain_n_Stream_Gauges", 3),
    "gauges_rain_stream": ("Rain_n_Stream_Gauges", 4),
}


def _fetch_arcgis_layer(service: str, layer: int) -> list[dict]:
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


def hcdd1_layer_url(name: str) -> str:
    service, layer = HCDD1_LAYERS[name]
    return f"{HCDD1_BASE}/{service}/FeatureServer/{layer}"


def hcdd1_layer(name: str, cache_dir: Path = DOWNLOAD_CACHE / "hcdd1", *, force: bool = False) -> list[dict]:
    """The GeoJSON features of one drainage-district layer (a key of HCDD1_LAYERS)."""
    cached = cache_dir / f"{name}.geojson"
    if not already_have(cached, force=force):
        features = _fetch_arcgis_layer(*HCDD1_LAYERS[name])
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(feature_collection(features)), encoding="utf-8")
        print(f"  [ok]   {name}: {len(features)} features", flush=True)
        return features
    return json.loads(cached.read_text(encoding="utf-8"))["features"]


def _fetch_attachment_groups(layer_url: str) -> list[dict]:
    """A layer's attachment listing: one group per feature that has files
    attached. Empty for a layer that doesn't carry attachments at all."""
    groups: list[dict] = []
    while True:
        params = {"definitionExpression": "1=1", "resultOffset": len(groups), "resultRecordCount": 2000, "f": "json"}
        page = get_json(f"{layer_url}/queryAttachments?{urllib.parse.urlencode(params)}", timeout=120)
        if "error" in page:  # "Layer does not support attachments."
            return groups
        groups += page.get("attachmentGroups", [])
        if not page.get("exceededTransferLimit") or not page.get("attachmentGroups"):
            return groups


def hcdd1_image_urls(name: str, cache_dir: Path = DOWNLOAD_CACHE / "hcdd1", *, force: bool = False) -> dict[int, str]:
    """Feature id -> address of the image the district attached to that feature.

    The district publishes the actual photo for some of its photo layers and
    only a path on its own network for the rest, so this is empty for those.
    Only the listing is downloaded; the images stay on the district's server.
    """
    cached = cache_dir / f"{name}.attachments.json"
    layer_url = hcdd1_layer_url(name)
    if already_have(cached, force=force):
        groups = json.loads(cached.read_text(encoding="utf-8"))
    else:
        groups = _fetch_attachment_groups(layer_url)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(groups), encoding="utf-8")
        print(f"  [ok]   {name}: {len(groups)} features with attachments", flush=True)
    urls = {}
    for group in groups:
        images = [a for a in group["attachmentInfos"] if a.get("contentType", "").startswith("image/")]
        if images:
            urls[group["parentObjectId"]] = f"{layer_url}/{group['parentObjectId']}/attachments/{images[0]['id']}"
    return urls


# ---- OpenFEMA ---------------------------------------------------------------

OPENFEMA = "https://www.fema.gov/api/open"


def export_openfema(dataset: str, version: str, dest: Path, *, select: str = "") -> int:
    """The four counties' rows of an OpenFEMA dataset as NDJSON, via its file-export
    endpoint.

    Without `$top` the `.jsonl` endpoint streams every matching row in one response,
    so there is no paging (deep `$skip` queries time out on the big tables). Each
    county is its own request, kept in a parts folder so an interrupted run resumes
    where it stopped instead of starting over.
    """
    parts = dest.parent / f".{dest.stem}-parts"
    for slug, county in COUNTIES.items():
        params = {"$filter": f"countyCode eq '{county['fips']}'"}
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


def nfip_claims(cache_dir: Path = DOWNLOAD_CACHE / "nfip", *, force: bool = False) -> Path:
    """FEMA's NFIP claims (v3) for the four counties, one JSON claim per line."""
    cached = cache_dir / "nfip_claims_v3.ndjson"
    if not already_have(cached, force=force):
        cached.parent.mkdir(parents=True, exist_ok=True)
        print(f"  [ok]   claims: {export_openfema('NfipClaims', 'v3', cached)}", flush=True)
    return cached


# ---- Census tracts ----------------------------------------------------------

# Claims carry tract ids from both vintages, so both boundary sets are needed.
TRACT_FILES = {
    2023: "https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_48_tract.zip",
    2010: "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_48_tract10.zip",
}


def census_tracts(vintage: int, cache_dir: Path = DOWNLOAD_CACHE / "tracts", *, force: bool = False) -> Path:
    """The Census TIGER shapefile (zipped) of Texas tracts for a vintage."""
    url = TRACT_FILES[vintage]
    cached = cache_dir / url.rsplit("/", 1)[-1]
    download(url, cached, force=force)
    return cached
