"""Map layers that cover all four counties the way the drainage district's
layers cover Hidalgo: the drains, canals and creeks; the flood works the State
Flood Plan records; the flood projects it lists; the two cities that publish
their storm drainage; and the flooding the National Weather Service was told
about.

Sources are pulled by `public_sources.py` and `overture.py` (and, for the
storm reports, read back from the database `build_history.py` filled). Where two
sources map the same thing, the one with more to say about it is kept: the
drainage district's and cities' ditches over the Census lines along them, and
the state's dam inventory over Overture's. Every feature is kept only
where it touches one of the four counties, tested against the county's real
boundary, and carries that county's name.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import geopandas as gpd
import overture
import shapely
from database import MapLayer
from jsonio import feature_collection
from paths import DATABASE, county_boundary
from public_sources import (
    census_places,
    census_water_lines,
    city_drainage_layer,
    commons_flood_photos,
    hcdd1_layer,
    twdb_flood_plan_layer,
)
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from rgv_flood.counties import COUNTIES, SHORT_NAMES

# Degrees; ~0.00005 is about 5 m, well under what the map can show for a ditch.
TOLERANCE = 0.00005


def _county_polygons() -> dict[str, shapely.Geometry]:
    polygons = {slug: shape(county_boundary(slug)) for slug in COUNTIES}
    for polygon in polygons.values():
        shapely.prepare(polygon)  # many intersects tests against the same polygon
    return polygons


def _county_of(geometry: shapely.Geometry, polygons: dict[str, shapely.Geometry]) -> str | None:
    """The county a feature belongs to: the one holding its representative
    point, or, for a feature that only grazes the area, the first it touches."""
    point = geometry.representative_point()
    touching = [slug for slug, polygon in polygons.items() if polygon.intersects(geometry)]
    return next((slug for slug in touching if polygons[slug].contains(point)), touching[0] if touching else None)


def _feature(geometry: shapely.Geometry, properties: dict) -> dict:
    simplified = geometry if geometry.geom_type == "Point" else geometry.simplify(TOLERANCE, preserve_topology=True)
    return {
        "type": "Feature",
        "geometry": json.loads(shapely.to_geojson(shapely.set_precision(simplified, 0.00001))),
        "properties": {key: value for key, value in properties.items() if value not in (None, "")},
    }


def _layer(features: list[dict]) -> MapLayer | None:
    if not features:
        return None
    return MapLayer(json.dumps(feature_collection(features), separators=(",", ":")), len(features))


def _in_counties(source_features: list[dict], to_properties, polygons) -> list[dict]:
    """Source GeoJSON features that touch a county, rebuilt by `to_properties`
    (which may return None to leave a feature out)."""
    features = []
    for source in source_features:
        if not source.get("geometry"):
            continue
        geometry = shape(source["geometry"])
        county = _county_of(geometry, polygons)
        properties = to_properties(source["properties"]) if county else None
        if properties is not None:
            features.append(_feature(geometry, {**properties, "county": SHORT_NAMES[county]}))
    return features


def _text(value: object, limit: int = 400) -> str | None:
    """Source text as published, minus the U+FFFD marks a lost character left behind."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.replace("�", "").strip()[:limit]


# ---- waterways (Census) ------------------------------------------------------

# How a canal or ditch's own name says what it is for. Checked in order.
WATERWAY_NAMES = (
    (re.compile(r"\b(drn|drain|drainage|ditch|floodway|relief)\b", re.IGNORECASE), "drain"),
    (re.compile(r"\bresaca\b", re.IGNORECASE), "resaca"),
    (re.compile(r"\b(cnl|canal|lateral|irr|irrigation|supply)\b", re.IGNORECASE), "canal"),
)


def _waterway_kind(mtfcc: str, name: str | None) -> str | None:
    """Census feature class: H3010 stream or river, H3013 braided stream,
    H3020 canal, ditch or aqueduct. Anything else (connectors) is not drawn."""
    if mtfcc in ("H3010", "H3013"):
        return "resaca" if name and re.search(r"\bresaca\b", name, re.IGNORECASE) else "creek"
    if mtfcc != "H3020":
        return None
    for pattern, kind in WATERWAY_NAMES:
        if name and pattern.search(name):
            return kind
    return "canal_or_ditch"


# Where the drainage district or a city maps a ditch, its line (with the
# ditch's own name and owner) is drawn and the Census line along it is left
# out: a Census line is the same ditch when this share of it runs within
# about 100 m of a local one.
SAME_DITCH_SHARE = 0.8
NEAR_DEGREES = 0.0009  # ~100 m


def _local_ditches() -> shapely.Geometry:
    """The area within ~100 m of a ditch the drainage district or a city maps."""
    sources = [
        *hcdd1_layer("drainage_system"),
        *city_drainage_layer("harlingen_ditches"),
        *city_drainage_layer("brownsville_ditches"),
    ]
    area = shapely.union_all([shape(f["geometry"]) for f in sources if f.get("geometry")]).buffer(NEAR_DEGREES)
    shapely.prepare(area)
    return area


def _mapped_locally(line: shapely.Geometry, local_ditches: shapely.Geometry) -> bool:
    return line.length > 0 and line.intersection(local_ditches).length / line.length >= SAME_DITCH_SHARE


def build_waterways() -> MapLayer | None:
    """Drains, canals, resacas and creeks in each county (Census TIGER 2023),
    except those the drainage district or a city already maps."""
    local_ditches = _local_ditches()
    features = []
    for slug in COUNTIES:
        lines = gpd.read_file(f"zip://{census_water_lines(slug)}").to_crs(4326)
        for row in lines.itertuples():
            name = row.FULLNAME if isinstance(row.FULLNAME, str) else None
            kind = _waterway_kind(row.MTFCC, name)
            if not kind or row.geometry is None or row.geometry.is_empty:
                continue
            if not _mapped_locally(row.geometry, local_ditches):
                features.append(_feature(row.geometry, {
                    "overlay_type": "waterway", "kind": kind, "name": name, "county": SHORT_NAMES[slug],
                }))
    return _layer(features)


# ---- flood infrastructure (State Flood Plan) --------------------------------

INFRASTRUCTURE_KINDS = {
    "Dam": "dam",
    "Levee": "levee",
    "Sea Wall": "sea_wall",
    "Storm Drain System": "storm_drain",
    "LWC": "low_water_crossing",
}
# Land set aside rather than built: left out. (The plan's polygons, all lakes it
# calls ponds, parks and wetlands here, aren't downloaded at all.)
NOT_FLOOD_WORKS = {"Otherwise Protected Area"}
COASTAL_WORKS = re.compile(r"\b(dune|jetty|beach|revetments?)\b", re.IGNORECASE)
UNKNOWN = ("Unknown", "999999")


def _infrastructure(p: dict) -> dict | None:
    description = _text(p.get("DESCR"))
    if description in NOT_FLOOD_WORKS:
        return None
    kind = INFRASTRUCTURE_KINDS.get(p.get("INFRA_TYPE"))
    if not kind:
        kind = "coastal" if description and COASTAL_WORKS.search(description) else "other"
    return {
        "overlay_type": "flood_infrastructure",
        "kind": kind,
        "name": _text(p.get("NAME"), 120),
        "description": description,
        "condition": None if p.get("CONDITION") in UNKNOWN else _text(p.get("CONDITION"), 60),
    }


# Overture Maps (from OpenStreetMap) has dams the state inventory lacks, such
# as the Retamal Diversion Dam on the Rio Grande. One within ~300 m of a state
# dam is the same dam; one without a name (mostly stock-tank dams in Starr)
# can't be checked, so it is left out.
SAME_DAM_DEGREES = 0.003


def _dams_the_state_lacks(state_dams: list[shapely.Geometry], polygons) -> list[dict]:
    known = STRtree(state_dams)
    features = []
    for geometry, attributes in overture.bridges_and_dams():
        name = (attributes.get("names") or {}).get("primary")
        if attributes["class"] != "dam" or not name:
            continue
        if len(known.query(geometry, predicate="dwithin", distance=SAME_DAM_DEGREES)):
            continue
        if county := _county_of(geometry, polygons):
            features.append(_feature(geometry, {
                "overlay_type": "flood_infrastructure", "kind": "dam", "name": name,
                "source": "Overture Maps Foundation", "county": SHORT_NAMES[county],
            }))
    return features


def build_flood_infrastructure() -> MapLayer | None:
    """Dams, levees, sea walls, storm drain systems, low-water crossings and
    coastal works the 2024 State Flood Plan inventories in the four counties,
    plus the named dams it lacks that Overture Maps has."""
    polygons = _county_polygons()
    features = []
    for name in ("infrastructure_lines", "infrastructure_points"):  # points drawn last, on top
        features += _in_counties(twdb_flood_plan_layer(name), _infrastructure, polygons)
    state_dams = [shape(f["geometry"]) for f in features if f["properties"]["kind"] == "dam"]
    features += _dams_the_state_lacks(state_dams, polygons)
    return _layer(features)


# ---- flood projects (State Flood Plan) --------------------------------------


def _ongoing_project(p: dict) -> dict:
    return {
        "overlay_type": "flood_project",
        "stage": "ongoing",
        "name": _text(p.get("EXPRJNAME"), 160),
        "description": _text(p.get("EXPRJDESC")),
        "cost": p.get("COST"),
        "funding": _text(p.get("FUND_SRC"), 80),
        "year": p.get("COMP_YR"),
    }


def _recommended_project(p: dict) -> dict:
    return {
        "overlay_type": "flood_project",
        "stage": "recommended",
        "name": _text(p.get("FMP_NAME"), 160),
        "description": _text(p.get("FMP_DESCR")),
        "cost": p.get("FMP_COST"),
        "project_type": _text(p.get("FMP_TYPE"), 60),
        "structures_at_risk": p.get("STRUCT_100"),
        "structures_still_at_risk": p.get("REMSTRC100"),
    }


def build_flood_projects() -> MapLayer | None:
    """Flood projects the state plan lists: ongoing ones local governments
    reported, and new ones the regional planning group recommended."""
    polygons = _county_polygons()
    features = _in_counties(twdb_flood_plan_layer("ongoing_projects"), _ongoing_project, polygons)
    features += _in_counties(twdb_flood_plan_layer("recommended_projects"), _recommended_project, polygons)
    return _layer(features)


# ---- city storm drainage (Harlingen, Brownsville) ----------------------------

# Harlingen records each ditch's owner as a short code. Only the codes whose
# meaning is certain are spelled out; any other code is shown as published.
OWNER_CODES = {"COH": "City of Harlingen", "CC": "Cameron County", "TXDOT": "TxDOT"}
DRAINAGE_DISTRICT_CODE = re.compile(r"^CCDD(\d+)$")


def _owner(code: object) -> str | None:
    code = _text(code, 80)
    if not code:
        return None
    if district := DRAINAGE_DISTRICT_CODE.match(code.upper()):
        return f"Cameron County Drainage District No. {district.group(1)}"
    return OWNER_CODES.get(code.upper(), code)


def _ditch_name(name: object, owner_code: object = None) -> str | None:
    """A ditch's own name, or None where the field holds a placeholder or just repeats the owner code."""
    name = _text(name, 80)
    if not name or name in ("0", "Unknown") or name == _text(owner_code, 80):
        return None
    return name


def build_city_drainage() -> MapLayer | None:
    """The storm drainage the cities of Harlingen and Brownsville publish."""
    polygons = _county_polygons()

    def harlingen_ditch(p: dict) -> dict:
        return {"overlay_type": "city_drainage", "kind": "ditch", "city": "Harlingen",
                "name": _ditch_name(p.get("DD_Name"), p.get("Owner")), "owner": _owner(p.get("Owner"))}

    def harlingen_pond(_p: dict) -> dict:
        return {"overlay_type": "city_drainage", "kind": "detention_pond", "city": "Harlingen"}

    def harlingen_sewer(p: dict) -> dict:
        size = _text(p.get("SIZE"), 12)
        return {"overlay_type": "city_drainage", "kind": "storm_sewer", "city": "Harlingen",
                "size": f"{size} in" if size and size.isdigit() else size, "material": _text(p.get("MATERIAL"), 20)}

    def brownsville_ditch(p: dict) -> dict:
        return {"overlay_type": "city_drainage", "kind": "ditch", "city": "Brownsville",
                "name": _ditch_name(p.get("NAME")), "owner": _text(p.get("DISTRICT"), 80)}

    features = []
    for name, to_properties in (
        ("harlingen_storm_sewers", harlingen_sewer),
        ("harlingen_ditches", harlingen_ditch),
        ("brownsville_ditches", brownsville_ditch),
        ("harlingen_detention_ponds", harlingen_pond),
    ):
        features += _in_counties(city_drainage_layer(name), to_properties, polygons)
    return _layer(features)


# ---- FEMA flood photos (Wikimedia Commons) ----------------------------------

# A FEMA caption starts with the place and date: "Raymondville, TX, July 25,
# 2008 -- Flood waters remain ...". That place is the only location a photo
# has, so photos are grouped by town and drawn at the Census point for it.
CAPTION_PLACE = re.compile(r"^\s*([A-Za-z .']+?)\s*,\s*(?:TX|Texas)\b")
# Place names as FEMA's captions misspell them.
PLACE_SPELLINGS = {
    "Welasco": "Weslaco",
    "Wesllaco": "Weslaco",
    "Harlinger": "Harlingen",
    "Harlingren": "Harlingen",
    "Edingburg": "Edinburg",
    "Rio Grende City": "Rio Grande City",
    "Point Isabel": "Port Isabel",
}
# Whether a photo shows flooding is judged from what FEMA says it shows: the
# file's title and the caption's first sentence. Later sentences often mention
# the flood when the photo is of a relief line, an office or a press briefing.
SHOWS_FLOODING = re.compile(r"flood|submerg|high water|waters recede", re.IGNORECASE)
NOT_FLOODING = re.compile(
    r"\b(DRC|Disaster Recovery Center|EOC|Operations? Center|TV|television|media|interview|meetings?|meets?|"
    r"talks?|speaks?|volunteers?)\b",
    re.IGNORECASE,
)
FEMA_TITLE = re.compile(r"^File:(FEMA - \d+ - )?|\.\w+$")
PLACE_KIND = re.compile(r" (city|town|village|CDP)$")


def _places() -> dict[str, Point]:
    """Texas place name -> the Census Bureau's internal point for it."""
    places = {}
    with census_places().open(encoding="utf-8") as gazetteer:
        header = next(gazetteer).rstrip().split("\t")
        for line in gazetteer:
            row = dict(zip(header, (value.strip() for value in line.split("\t")), strict=False))
            places[PLACE_KIND.sub("", row["NAME"])] = Point(float(row["INTPTLONG"]), float(row["INTPTLAT"]))
    return places


def _scene(photo: dict) -> str:
    """What a photo shows, in FEMA's words: its title and the caption's first sentence."""
    first_sentence = photo["caption"].partition("--")[2].strip().split(". ")[0]
    return f"{FEMA_TITLE.sub('', photo['title'])}. {first_sentence}"


def _flood_photo(photo: dict) -> tuple[str, dict] | None:
    """(town, photo) for a FEMA photo of flooding whose caption names a town."""
    caption, scene = photo["caption"], _scene(photo)
    named = CAPTION_PLACE.match(caption)
    if not named or not photo.get("thumb_url") or not SHOWS_FLOODING.search(scene) or NOT_FLOODING.search(scene):
        return None
    town = PLACE_SPELLINGS.get(named.group(1).strip(), named.group(1).strip())
    return town, {
        "taken": photo["taken"] or None,
        "caption": caption[:400],
        "credit": photo["artist"] or "FEMA",
        "thumb_url": photo["thumb_url"],
        "page_url": photo["page_url"],
    }


def build_fema_flood_photos() -> MapLayer | None:
    """FEMA's photos of flooding in the four counties, one dot per town."""
    polygons, places = _county_polygons(), _places()
    by_town: dict[str, list[dict]] = {}
    for source in commons_flood_photos():
        if found := _flood_photo(source):
            by_town.setdefault(found[0], []).append(found[1])
    features = []
    for town, photos in sorted(by_town.items()):
        point = places.get(town)
        county = _county_of(point, polygons) if point else None
        if county:
            features.append(_feature(point, {
                "overlay_type": "fema_photos", "town": town, "county": SHORT_NAMES[county],
                "photos": sorted(photos, key=lambda photo: photo["taken"] or ""),
            }))
    return _layer(features)


# ---- NWS flood reports -----------------------------------------------------


def build_nws_flood_reports(database: Path = DATABASE) -> MapLayer | None:
    """The flood reports build_events.py loaded from the NWS storm-report archive."""
    if not database.exists():
        return None
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("select * from nws_flood_reports order by reported_at").fetchall()
        except sqlite3.OperationalError:  # build_events.py hasn't run yet
            return None
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": {
                key: row[key] for key in ("kind", "reported_at", "city", "remark", "source", "magnitude")
                if row[key] not in (None, "")
            } | {"overlay_type": "storm_report", "county": SHORT_NAMES[row["county"]]},
        }
        for row in rows
        if row["lat"] is not None
    ]
    return _layer(features)
