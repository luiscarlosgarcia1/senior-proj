"""Public datasets the build downloads: ArcGIS layers from the Hidalgo drainage
district, the state flood plan and two cities; FEMA's NFIP claims; Census
tracts and water lines; and the National Weather Service's storm reports.

Each function returns data that is downloaded once and kept in a cache folder
exactly as the publisher sent it. The map build uses the default cache under
`tmp/`; `fetch_ml_inputs.py` passes its own folder for the layers it shares.
"""

from __future__ import annotations

import json
import re
import shutil
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from jsonio import feature_collection
from net import already_have, download, get_json
from paths import DOWNLOAD_CACHE

from rgv_flood.counties import COUNTIES, RGV_BBOX

# ---- ArcGIS feature layers ----------------------------------------------------


def fetch_arcgis_features(layer_url: str, *, where: str = "1=1", in_rgv: bool = False) -> list[dict]:
    """Every feature of one ArcGIS layer as GeoJSON, paged because servers cap
    how many features one response may carry. `in_rgv` asks the server for only
    the features touching the four-county bounding box."""
    params = {"where": where, "outFields": "*", "outSR": "4326", "f": "geojson", "resultRecordCount": 1000}
    if in_rgv:
        params |= {
            "geometry": ",".join(map(str, RGV_BBOX)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }
    features: list[dict] = []
    while True:
        page = get_json(f"{layer_url}/query?{urllib.parse.urlencode(params | {'resultOffset': len(features)})}", timeout=120)
        if not page.get("features"):
            return features
        features += page["features"]


def _cached_features(cached: Path, fetch: Callable[[], list[dict]], *, force: bool = False) -> list[dict]:
    """Features fetched once and then read back from `cached`."""
    if already_have(cached, force=force):
        return json.loads(cached.read_text(encoding="utf-8"))["features"]
    features = fetch()
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(feature_collection(features)), encoding="utf-8")
    print(f"  [ok]   {cached.stem}: {len(features)} features", flush=True)
    return features

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


def hcdd1_layer_url(name: str) -> str:
    service, layer = HCDD1_LAYERS[name]
    return f"{HCDD1_BASE}/{service}/FeatureServer/{layer}"


def hcdd1_layer(name: str, cache_dir: Path = DOWNLOAD_CACHE / "hcdd1", *, force: bool = False) -> list[dict]:
    """The GeoJSON features of one drainage-district layer (a key of HCDD1_LAYERS)."""
    return _cached_features(cache_dir / f"{name}.geojson", lambda: fetch_arcgis_features(hcdd1_layer_url(name)), force=force)


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


# ---- Texas Water Development Board: the 2024 State Flood Plan ---------------

TWDB_FLOOD_PLAN = "https://gis2.twdb.texas.gov/server/rest/services/OOP_FP_SFPV/Data_Download/FeatureServer"

# Our name -> (layer id, which features to ask for). The plan maps wetlands as
# "infrastructure" too, by the thousand; they are natural features, not flood
# works, so they are never downloaded.
TWDB_LAYERS = {
    "infrastructure_points": (9, "1=1"),
    "infrastructure_lines": (7, "1=1"),
    "ongoing_projects": (10, "1=1"),
    "recommended_projects": (12, "1=1"),
}


def twdb_flood_plan_layer(name: str, cache_dir: Path = DOWNLOAD_CACHE / "twdb", *, force: bool = False) -> list[dict]:
    """One State Flood Plan layer's features around the four counties."""
    layer, where = TWDB_LAYERS[name]

    def fetch() -> list[dict]:
        return fetch_arcgis_features(f"{TWDB_FLOOD_PLAN}/{layer}", where=where, in_rgv=True)

    return _cached_features(cache_dir / f"{name}.geojson", fetch, force=force)


# ---- City storm drainage (Cameron County) ----------------------------------

HARLINGEN_STORM_DRAIN = "https://services3.arcgis.com/gSCPzHZGMdbiljnH/arcgis/rest/services/Storm_Drain/FeatureServer"
BROWNSVILLE_DRAINAGE = "https://services2.arcgis.com/6oaLMZEZlktbQpyi/arcgis/rest/services/Drainage_Ownership/FeatureServer"
CITY_DRAINAGE_LAYERS = {
    "harlingen_ditches": f"{HARLINGEN_STORM_DRAIN}/6",
    "harlingen_detention_ponds": f"{HARLINGEN_STORM_DRAIN}/9",
    "harlingen_storm_sewers": f"{HARLINGEN_STORM_DRAIN}/7",
    "brownsville_ditches": f"{BROWNSVILLE_DRAINAGE}/1",
}


def city_drainage_layer(name: str, cache_dir: Path = DOWNLOAD_CACHE / "cities", *, force: bool = False) -> list[dict]:
    """One of the cities' published drainage layers (a key of CITY_DRAINAGE_LAYERS)."""
    return _cached_features(
        cache_dir / f"{name}.geojson", lambda: fetch_arcgis_features(CITY_DRAINAGE_LAYERS[name]), force=force
    )


# ---- National Weather Service storm reports -------------------------------

# Iowa Environmental Mesonet keeps the full archive of NWS Local Storm Reports.
# NWS Brownsville (BRO) covers all four counties; its online archive starts in 2005.
IEM_STORM_REPORTS = "https://mesonet.agron.iastate.edu/geojson/lsr.php"
STORM_REPORTS_SINCE = "2005-01-01"
STORM_REPORTS_FILE = DOWNLOAD_CACHE / "nws" / "local-storm-reports-bro.geojson"


def nws_storm_reports(cached: Path = STORM_REPORTS_FILE, *, force: bool = False) -> list[dict]:
    """Every Local Storm Report NWS Brownsville has issued, as GeoJSON features.
    (Hail, wind and the rest included; the caller keeps the kinds it wants.)"""
    def fetch() -> list[dict]:
        until = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
        params = {"wfos": "BRO", "sts": f"{STORM_REPORTS_SINCE}T00:00Z", "ets": until}
        return get_json(f"{IEM_STORM_REPORTS}?{urllib.parse.urlencode(params)}", timeout=180, attempts=3)["features"]

    return _cached_features(cached, fetch, force=force)


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


def census_water_lines(slug: str, cache_dir: Path = DOWNLOAD_CACHE / "tiger", *, force: bool = False) -> Path:
    """The Census TIGER 2023 linear-water shapefile (zipped) for one county:
    canals, ditches, drains, creeks and rivers."""
    name = f"tl_2023_{COUNTIES[slug]['fips']}_linearwater.zip"
    cached = cache_dir / name
    download(f"https://www2.census.gov/geo/tiger/TIGER2023/LINEARWATER/{name}", cached, force=force)
    return cached


def census_places(cached: Path = DOWNLOAD_CACHE / "census" / "2023_gaz_place_48.txt", *, force: bool = False) -> Path:
    """The Census Bureau's 2023 gazetteer of Texas places: each city, town and
    census-designated place with its official internal point."""
    download("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_gaz_place_48.txt", cached, force=force)
    return cached


# ---- FEMA flood photos (Wikimedia Commons) ----------------------------------

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# FEMA's photographs of the valley's floods, as Wikimedia Commons keeps them.
# They are public domain (the work of a U.S. federal agency).
COMMONS_FLOOD_CATEGORIES = (
    "Category:Effects of Hurricane Dolly (2008) in Texas",
    "Category:Images from FEMA, Hurricane Alex in Texas",
)
COMMONS_PHOTOS_FILE = DOWNLOAD_CACHE / "commons" / "fema-flood-photos.json"
THUMBNAIL_WIDTH = 500  # twice the popup width; Commons serves this size as is


def _commons(params: dict) -> dict:
    return get_json(f"{COMMONS_API}?{urllib.parse.urlencode({'action': 'query', 'format': 'json', **params})}", attempts=3)


def _plain(html: str | None) -> str:
    """Commons metadata is HTML; the text of it, on one line."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def commons_flood_photos(cached: Path = COMMONS_PHOTOS_FILE, *, force: bool = False) -> list[dict]:
    """Every photo in COMMONS_FLOOD_CATEGORIES with its caption, photographer,
    date, license, page and a thumbnail address."""
    if already_have(cached, force=force):
        return json.loads(cached.read_text(encoding="utf-8"))
    photos = []
    for category in COMMONS_FLOOD_CATEGORIES:
        listing = {"list": "categorymembers", "cmtitle": category, "cmtype": "file", "cmlimit": 500}
        titles: list[str] = []
        while True:
            page = _commons(listing)
            titles += [member["title"] for member in page["query"]["categorymembers"]]
            if "continue" not in page:
                break
            listing |= page["continue"]
        for start in range(0, len(titles), 50):  # the API's limit per request
            batch = _commons({"titles": "|".join(titles[start:start + 50]), "prop": "imageinfo",
                              "iiprop": "url|extmetadata", "iiurlwidth": THUMBNAIL_WIDTH})
            for file in batch["query"]["pages"].values():
                info = (file.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata", {})
                photos.append({
                    "title": file["title"],
                    "category": category,
                    "caption": _plain(meta.get("ImageDescription", {}).get("value")),
                    "artist": _plain(meta.get("Artist", {}).get("value")),
                    "taken": _plain(meta.get("DateTimeOriginal", {}).get("value"))[:10],
                    "license": _plain(meta.get("LicenseShortName", {}).get("value")),
                    "page_url": info.get("descriptionurl"),
                    "thumb_url": (info.get("thumburl") or "").split("?")[0] or None,  # minus tracking parameters
                })
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(photos), encoding="utf-8")
    print(f"  [ok]   {cached.stem}: {len(photos)} photos", flush=True)
    return photos
