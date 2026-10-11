"""Map layers built from the Hidalgo drainage district's published data and
FEMA NFIP claims: recorded flooding, flood photos, the drainage network, bond
projects, and insurance claims per census tract.

Inputs live in data/ml/raw/ (fetched by pipeline/fetch_ml_inputs.py, gitignored).
Every builder returns None when its inputs are missing, so a clone that hasn't
run the fetch script still builds the other layers.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
from app_db import MapLayer
from jsonio import feature_collection, read_ndjson
from paths import ML_RAW
from shapely.geometry import mapping, shape

from rgv_flood.counties import FIPS_TO_SLUG, RGV_BBOX, SHORT_NAMES

HCDD1_DIR = ML_RAW / "hcdd1"
HCDD1_NAME = "Hidalgo County Drainage District No. 1"
# Degrees; ~0.00002 is about 2 m, enough to shrink files without visible change.
FINE = 0.00002

# HCDD1 publishes project status as codes in some layers and words in others
# (including the misspelling "Costruction" in the 2023 layer).
STATUS_NAMES = {
    "PD": "Pre-design", "Pre-Design": "Pre-design",
    "D": "Design", "Design": "Design",
    "C": "Construction", "Costruction": "Construction", "Construction": "Construction",
    "CL": "Complete", "Complete": "Complete",
}

Properties = Callable[[dict], dict]


def _hcdd1(name: str) -> list[dict]:
    path = HCDD1_DIR / f"{name}.geojson"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def _round_coords(coords, digits: int = 5):
    if isinstance(coords[0], (int, float)):
        return [round(c, digits) for c in coords[:2]]
    return [_round_coords(c, digits) for c in coords]


def _feature(geometry: dict | None, properties: dict, tolerance: float = 0.0) -> dict | None:
    """A rounded (and optionally simplified) GeoJSON feature, or None if empty."""
    if not geometry:
        return None
    if tolerance:
        simplified = shape(geometry).simplify(tolerance, preserve_topology=True)
        if simplified.is_empty:
            return None
        geometry = mapping(simplified)
    coordinates = _round_coords(geometry["coordinates"])
    return {
        "type": "Feature",
        "geometry": {"type": geometry["type"], "coordinates": coordinates},
        "properties": properties,
    }


def _convert(layer: str, overlay_type: str, to_properties: Properties, tolerance: float = 0.0) -> list[dict]:
    """Every feature of one HCDD1 layer, with properties rebuilt by `to_properties`."""
    converted = (
        _feature(f.get("geometry"), {"overlay_type": overlay_type, **to_properties(f["properties"])}, tolerance)
        for f in _hcdd1(layer)
    )
    return [feature for feature in converted if feature]


def _layer(features: list[dict]) -> MapLayer | None:
    if not features:
        return None
    return MapLayer(json.dumps(feature_collection(features), separators=(",", ":")), len(features))


# ---- flood extents and photos ----------------------------------------------

# HCDD1 labels each event with an inch range. It never says whether that is
# rainfall or flood depth, so the label is passed through and not interpreted.
FLOOD_EXTENTS = [
    ("flood_extent_2008_4to10in", 2008, '4"–10"'),
    ("flood_extent_2010_3to6in", 2010, '3"–6"'),
    ("flood_extent_2015_1to8in", 2015, '1"–8"'),
    ("flood_extent_2018_4to18in", 2018, '4"–18"'),
    ("flood_extent_2019_4to10in", 2019, '4"–10"'),
    ("flood_extent_2020_8to14in", 2020, '8"–14"'),
]

FLOOD_PHOTOS = [
    ("flood_photos_2018_june", "June 2018"),
    ("flood_photos_2018_sept", "September 2018"),
    ("flood_photos_2019_june", "June 2019"),
    ("flood_photos_2020_hanna", "Hurricane Hanna 2020"),
    ("hanna_geotagged_photos", "Hurricane Hanna 2020"),
]


def build_hcdd1_flood_extents() -> MapLayer | None:
    """Areas the district mapped as flooded after six past storms (2008-2020)."""
    features = []
    for layer, year, label in FLOOD_EXTENTS:

        def properties(_p: dict, year=year, label=label) -> dict:
            return {"year": year, "hcdd1_label": label, "county": "Hidalgo", "source": HCDD1_NAME}

        features += _convert(layer, "flood_extent", properties, tolerance=0.00003)
    return _layer(features)


def _exif_to_text(exif_datetime: str) -> str:
    """'2018:06:21 17:56:48' -> '2018-06-21 17:56' (camera EXIF to readable)."""
    return exif_datetime[:16].replace(":", "-", 2)


def build_hcdd1_flood_photos() -> MapLayer | None:
    """Where and when the district photographed four floods. File paths and
    camera headings in the source are deliberately dropped."""
    west, south, east, north = RGV_BBOX  # drops photos with stray GPS tags
    features = []
    for layer, event in FLOOD_PHOTOS:
        for f in _hcdd1(layer):
            geometry = f.get("geometry")
            if not geometry or geometry["type"] != "Point":
                continue
            x, y = geometry["coordinates"][:2]
            if not (west < x < east and south < y < north):
                continue
            taken = _exif_to_text(f["properties"].get("DateTime") or "")
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(x, 5), round(y, 5)]},
                "properties": {"overlay_type": "flood_photo", "event": event, "taken": taken},
            })
    return _layer(features)


# ---- drainage network -------------------------------------------------------


def _channel(p: dict) -> dict:
    return {
        "kind": "channel",
        "name": p.get("Name") or p.get("AKA") or "Drainage channel",
        "owner": p.get("OwnOrMaint") or p.get("Owner") or "",
    }


def _planned_channel(p: dict) -> dict:
    return {
        "kind": "planned_channel",
        "name": p.get("Name") or p.get("Syst_Name") or "Planned channel",
        "owner": p.get("Status") or "",
    }


def _detention_pond(p: dict) -> dict:
    acres = p.get("Acreage")
    return {
        "kind": "detention_pond",
        "name": p.get("Name") or "Detention pond",
        "owner": p.get("Exist_Prop") or "",
        "acres": round(acres, 1) if isinstance(acres, (int, float)) else None,
    }


def _gate_or_pump(p: dict) -> dict:
    gate_type = (p.get("gate_type") or "").strip()
    is_pump = "pump" in gate_type.lower() or bool((p.get("pump_no") or "").strip())
    return {
        "kind": "pump" if is_pump else "gate",
        "name": (p.get("alias") or p.get("gate_id") or "Structure").strip(),
        "owner": gate_type,
    }


DRAINAGE_SOURCES = [
    ("drainage_system", _channel, FINE),
    ("future_system", _planned_channel, FINE),
    ("detention_ponds", _detention_pond, FINE),
    ("gates_pumps_new", _gate_or_pump, 0.0),
]


def build_hcdd1_drainage() -> MapLayer | None:
    """The district's channels, planned channels, detention ponds, gates and pumps."""
    features = []
    for layer, properties, tolerance in DRAINAGE_SOURCES:
        features += _convert(layer, "drainage", properties, tolerance)
    return _layer(features)


# ---- bond projects ----------------------------------------------------------

BOND_PROGRAMS = [("bond_2012", "2012 bond"), ("bond_2018", "2018 bond"), ("bond_2023", "2023 bond")]


def _year(epoch_ms) -> int | None:
    if not isinstance(epoch_ms, (int, float)):
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, UTC).year


def _bond_project(program: str) -> Properties:
    # The three bond layers name the same fields differently.
    def properties(p: dict) -> dict:
        title = p.get("ProjAreaNm") or p.get("Name") or p.get("NAME") or "Drainage project"
        description = p.get("Description") or p.get("Descript") or p.get("Summary") or ""
        return {
            "program": program,
            "name": title.strip(),
            "status": STATUS_NAMES.get(p.get("Proj_Status") or p.get("ProjStatus") or "", ""),
            "description": description.strip()[:400],
            "start_year": _year(p.get("Actl_Start")),
            "end_year": _year(p.get("Actl_End")),
            "precinct": str(p.get("Precinct") or ""),
        }

    return properties


def build_hcdd1_bond_projects() -> MapLayer | None:
    """Drainage projects funded by the 2012, 2018 and 2023 bonds, with status and dates."""
    features = []
    for layer, program in BOND_PROGRAMS:
        features += _convert(layer, "bond_project", _bond_project(program), FINE)
    return _layer(features)


# ---- NFIP claims by census tract -------------------------------------------

CLAIMS_FILE = ML_RAW / "nfip" / "nfip_claims_v3.ndjson"
TRACTS_2023 = ML_RAW / "tracts" / "tl_2023_48_tract.zip"
TRACTS_2010 = ML_RAW / "tracts" / "tl_2010_48_tract10.zip"
UTM_14N = 32614  # equal-area-ish metres for overlap weights


@dataclass
class _Tally:
    claims: float = 0.0
    paid: float = 0.0
    moved: float = 0.0  # claims that arrived from older tract boundaries
    years: set[int] = field(default_factory=set)
    events: Counter = field(default_factory=Counter)

    def add_share(self, other: _Tally, weight: float) -> None:
        self.claims += other.claims * weight
        self.paid += other.paid * weight
        self.moved += other.claims * weight
        self.years |= other.years
        for name, n in other.events.items():
            self.events[name] += n * weight


def _tally_claims(path: Path) -> dict[str, _Tally]:
    """Claims grouped by the 11-digit census tract in each claim's block-group id."""
    tallies: dict[str, _Tally] = {}
    for claim in read_ndjson(path):
        geoid = str(claim.get("censusGeoid") or "")[:11]
        if len(geoid) != 11:
            continue
        tally = tallies.setdefault(geoid, _Tally())
        tally.claims += 1
        tally.paid += (claim.get("amountPaidOnBuildingClaim") or 0) + (claim.get("amountPaidOnContentsClaim") or 0)
        if claim.get("yearOfLoss"):
            tally.years.add(claim["yearOfLoss"])
        if claim.get("floodEvent"):
            tally.events[claim["floodEvent"]] += 1
    return tallies


def _spread_old_tracts(old: dict[str, _Tally], tracts: gpd.GeoDataFrame, placed: dict[str, _Tally]) -> float:
    """Spread claims filed under 2010-vintage tract ids across the 2023 tracts that
    cover them, weighted by overlapping area. Returns how many claims moved."""
    old_shapes = gpd.read_file(f"zip://{TRACTS_2010}")
    old_shapes = old_shapes[old_shapes["GEOID10"].isin(old)][["GEOID10", "geometry"]].to_crs(UTM_14N)
    new_shapes = tracts[["GEOID", "geometry"]].to_crs(UTM_14N)
    pieces = gpd.overlay(old_shapes, new_shapes, how="intersection", keep_geom_type=True)
    area = pieces.geometry.area
    pieces["weight"] = area / area.groupby(pieces["GEOID10"]).transform("sum")
    moved = 0.0
    for piece in pieces.itertuples():
        placed.setdefault(piece.GEOID, _Tally()).add_share(old[piece.GEOID10], piece.weight)
        moved += old[piece.GEOID10].claims * piece.weight
    return moved


def _class_breaks(counts: list[int]) -> list[int]:
    """Quintile cut points over the non-zero claim counts."""
    ranked = sorted(n for n in counts if n)
    return [ranked[int(len(ranked) * q)] for q in (0.2, 0.4, 0.6, 0.8)] if ranked else []


def build_nfip_claims_by_tract() -> MapLayer | None:
    """NFIP flood-insurance claims per census tract, all four counties.

    Raw counts only: the policy file (needed to turn counts into a rate) is a
    separate, slower download, so tracts with many insured homes read high.
    About a third of claims carry 2010-vintage tract ids; those are spread
    across the current tracts by area instead of being dropped.
    """
    if not (CLAIMS_FILE.exists() and TRACTS_2023.exists()):
        return None

    by_geoid = _tally_claims(CLAIMS_FILE)
    total = sum(t.claims for t in by_geoid.values())

    tracts = gpd.read_file(f"zip://{TRACTS_2023}")
    tracts = tracts[tracts["GEOID"].str[:5].isin(FIPS_TO_SLUG)].to_crs(4326)
    known = set(tracts["GEOID"])
    placed = {geoid: t for geoid, t in by_geoid.items() if geoid in known}
    old = {geoid: t for geoid, t in by_geoid.items() if geoid not in known}

    moved = _spread_old_tracts(old, tracts, placed) if old and TRACTS_2010.exists() else 0.0
    print(f"  claims placed on a 2023 tract: {sum(t.claims for t in placed.values()):.0f}/{total:.0f}"
          f" (spread from old tracts: {moved:.0f})")

    breaks = _class_breaks([round(t.claims) for t in placed.values()])
    features = []
    for tract in tracts.itertuples():
        tally = placed.get(tract.GEOID, _Tally())
        claims = round(tally.claims)
        top_event = max(tally.events, key=tally.events.get) if tally.events else ""
        feature = _feature(
            tract.geometry.__geo_interface__,
            {
                "overlay_type": "claims",
                "geoid": tract.GEOID,
                "county": SHORT_NAMES[FIPS_TO_SLUG[tract.GEOID[:5]]],
                "claims": claims,
                "paid": round(tally.paid),
                "claims_class": 1 + bisect_left(breaks, claims) if claims else 0,
                "from_old_tracts": round(tally.moved),
                "first_year": min(tally.years) if tally.years else None,
                "last_year": max(tally.years) if tally.years else None,
                "top_event": top_event,
            },
            tolerance=0.0004,
        )
        if feature:
            features.append(feature)
    return _layer(features)
