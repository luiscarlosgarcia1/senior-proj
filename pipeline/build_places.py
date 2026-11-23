#!/usr/bin/env python3
"""Places for the chatbot: each Census city, town and census-designated place in
the four counties, the county holding most of it, and the census tracts that make
it up (both the 2010 and 2023 vintages, because NFIP claims carry tract ids from both).

Run:  uv run --group pipeline python pipeline/build_places.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import geopandas as gpd
from database import open_database, record_sources, replace_table
from paths import DATABASE, SEED_DIR, county_boundary
from public_sources import census_place_polygons, census_tracts
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rgv_flood.counties import COUNTIES

TRACT_SHARE_MIN = 0.2  # a tract belongs to a place when at least this much of its area is inside it
AREA_CRS = "EPSG:32614"  # UTM 14N: all four counties, in metres
ALIASES_SEED = "place-aliases.csv"


def place_rows(places: gpd.GeoDataFrame, counties: dict[str, BaseGeometry]) -> list[dict]:
    """One row per place lying mostly inside the given counties (EPSG:4326 geometries)."""
    county_frame = gpd.GeoDataFrame({"county": list(counties)}, geometry=list(counties.values()), crs="EPSG:4326")
    county_area = county_frame.to_crs(AREA_CRS)
    projected = places.to_crs(AREA_CRS)
    rows = []
    for (_, place), geom in zip(places.iterrows(), projected.geometry, strict=True):
        overlaps = {c: geom.intersection(g).area for c, g in zip(county_area["county"], county_area.geometry, strict=True)}
        county = max(overlaps, key=overlaps.get)
        if sum(overlaps.values()) < 0.5 * geom.area:
            continue
        point = place.geometry.representative_point()
        rows.append({
            "place_id": str(place["GEOID"]),
            "name": str(place["NAME"]),
            "full_name": str(place["NAMELSAD"]),
            "kind": "cdp" if str(place["CLASSFP"]).startswith("U") else "city",
            "county": county,
            "lon": round(point.x, 6),
            "lat": round(point.y, 6),
        })
    return rows


def tract_rows(places: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame, vintage: int) -> list[dict]:
    """(place, tract) pairs where at least TRACT_SHARE_MIN of the tract's area lies inside the place."""
    p = places[["GEOID", "geometry"]].rename(columns={"GEOID": "place_id"}).to_crs(AREA_CRS)
    geoid = "GEOID" if "GEOID" in tracts else "GEOID10"
    t = tracts[[geoid, "geometry"]].rename(columns={geoid: "tract"}).to_crs(AREA_CRS)
    t["tract_area"] = t.geometry.area
    pieces = gpd.overlay(t, p, how="intersection", keep_geom_type=True)
    pieces["share"] = pieces.geometry.area / pieces["tract_area"]
    pieces = pieces[pieces["share"] >= TRACT_SHARE_MIN]
    return [{"place_id": str(r.place_id), "tract": str(r.tract), "share_of_tract": round(float(r.share), 4),
             "vintage": vintage} for r in pieces.itertuples()]


def alias_rows(aliases: list[dict], places: list[dict]) -> list[dict]:
    """Seed aliases resolved to place ids by exact name; an alias naming no place is a build error."""
    by_name = {p["name"]: p["place_id"] for p in places}
    rows = []
    for alias in aliases:
        if alias["place_name"] not in by_name:
            raise ValueError(f"place alias {alias['alias']!r} names no place: {alias['place_name']!r}")
        rows.append({"alias": alias["alias"].strip().lower(), "place_id": by_name[alias["place_name"]]})
    return rows


def _four_county_tracts(vintage: int) -> gpd.GeoDataFrame:
    tracts = gpd.read_file(f"zip://{census_tracts(vintage).as_posix()}")
    county_col = "COUNTYFP" if "COUNTYFP" in tracts else "COUNTYFP10"
    fips = {c["fips"][2:] for c in COUNTIES.values()}
    return tracts[tracts[county_col].isin(fips)].to_crs("EPSG:4326")


def main(database: Path = DATABASE, seed_dir: Path = SEED_DIR) -> None:
    counties = {slug: shape(county_boundary(slug, seed_dir)) for slug in COUNTIES}
    all_places = gpd.read_file(f"zip://{census_place_polygons().as_posix()}").to_crs("EPSG:4326")
    nearby = all_places[all_places.intersects(gpd.GeoSeries(list(counties.values()), crs="EPSG:4326").union_all())]
    places = place_rows(nearby, counties)
    kept = nearby[nearby["GEOID"].astype(str).isin({p["place_id"] for p in places})]
    tracts = [row for vintage in (2010, 2023) for row in tract_rows(kept, _four_county_tracts(vintage), vintage)]
    with (seed_dir / ALIASES_SEED).open(encoding="utf-8", newline="") as handle:
        aliases = alias_rows(list(csv.DictReader(handle)), places)

    with open_database(database) as connection:
        replace_table(connection, "places", places)
        replace_table(connection, "place_tracts", tracts)
        replace_table(connection, "place_aliases", aliases)
        record_sources(connection, [{
            "id": "census-places", "publisher": "U.S. Census Bureau",
            "dataset": "TIGER/Line 2023 places, with 2010 and 2023 census tracts",
            "url": "https://www2.census.gov/geo/tiger/TIGER2023/PLACE/", "retrieved_at": None,
            "record_count": len(places),
            "notes": f"A tract belongs to a place when at least {TRACT_SHARE_MIN:.0%} of its area is inside it.",
        }])
    print(f"places: {len(places)}; place_tracts: {len(tracts)}; place_aliases: {len(aliases)}")
    print("written to", database)


if __name__ == "__main__":
    main()
