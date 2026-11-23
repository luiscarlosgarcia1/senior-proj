"""Places and their census tracts, built from synthetic polygons (no downloads)."""

import sqlite3
from contextlib import closing

import geopandas as gpd
import pytest
from build_places import TRACT_SHARE_MIN, alias_rows, place_rows, tract_rows
from database import ensure_schema
from shapely.geometry import box

HIDALGO = box(-98.6, 26.0, -97.9, 26.8)
CAMERON = box(-97.9, 25.8, -97.1, 26.4)


def places_frame(*rows):
    """rows of (GEOID, NAME, NAMELSAD, CLASSFP, geometry)."""
    return gpd.GeoDataFrame(
        {"GEOID": [r[0] for r in rows], "NAME": [r[1] for r in rows], "NAMELSAD": [r[2] for r in rows],
         "CLASSFP": [r[3] for r in rows]},
        geometry=[r[4] for r in rows], crs="EPSG:4326",
    )


def test_threshold_from_spec():
    assert TRACT_SHARE_MIN == 0.2


def test_tract_share_threshold():
    place = places_frame(("4824464", "Edinburg", "Edinburg city", "C1", box(-98.20, 26.30, -98.17, 26.40)))
    tracts = gpd.GeoDataFrame(
        {"GEOID": ["48215000100", "48215000200", "48215000300"]},
        geometry=[
            box(-98.20, 26.30, -98.10, 26.40),  # 30% inside the place
            box(-98.17, 26.30, -97.90, 26.40),  # only touches it
            box(-98.18, 26.30, -98.08, 26.40),  # 10% inside
        ],
        crs="EPSG:4326",
    )
    rows = tract_rows(place, tracts, vintage=2023)
    assert {(r["tract"], r["vintage"]) for r in rows} == {("48215000100", 2023)}
    assert rows[0]["place_id"] == "4824464"
    assert rows[0]["share_of_tract"] == pytest.approx(0.30, abs=0.01)


def test_place_county_is_majority_area():
    straddling = places_frame(("4800001", "Edge", "Edge city", "C1", box(-98.04, 26.1, -97.84, 26.2)))  # 70% hidalgo
    rows = place_rows(straddling, {"hidalgo": HIDALGO, "cameron": CAMERON})
    assert rows[0]["county"] == "hidalgo"
    assert rows[0]["name"] == "Edge" and rows[0]["full_name"] == "Edge city"
    assert -98.04 < rows[0]["lon"] < -97.84 and 26.1 < rows[0]["lat"] < 26.2


def test_places_outside_the_four_counties_are_dropped():
    far = places_frame(("4835000", "Houston", "Houston city", "C1", box(-95.5, 29.6, -95.2, 29.9)))
    assert place_rows(far, {"hidalgo": HIDALGO, "cameron": CAMERON}) == []


def test_cdp_kind():
    frame = places_frame(("4800002", "La Mission", "La Mission CDP", "U1", box(-98.3, 26.2, -98.29, 26.21)),
                         ("4800003", "Mission", "Mission city", "C1", box(-98.33, 26.2, -98.31, 26.22)))
    kinds = {r["name"]: r["kind"] for r in place_rows(frame, {"hidalgo": HIDALGO})}
    assert kinds == {"La Mission": "cdp", "Mission": "city"}


def test_alias_rows_resolve_by_name():
    places = [{"place_id": "4857000", "name": "Peñitas"}]
    assert alias_rows([{"alias": "penitas", "place_name": "Peñitas"}], places) == [
        {"alias": "penitas", "place_id": "4857000"}]


def test_alias_naming_no_place_fails():
    with pytest.raises(ValueError, match="Nowhere"):
        alias_rows([{"alias": "nowhere", "place_name": "Nowhere"}], [{"place_id": "1", "name": "Edinburg"}])


def test_schema_has_places_tables():
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection)
        columns = {t: [r[1] for r in connection.execute(f"pragma table_info({t})")]
                   for t in ("places", "place_tracts", "place_aliases")}
    assert columns["places"] == ["place_id", "name", "full_name", "kind", "county", "lon", "lat"]
    assert columns["place_tracts"] == ["place_id", "tract", "share_of_tract", "vintage"]
    assert columns["place_aliases"] == ["alias", "place_id"]


def test_same_tract_in_both_vintages_can_be_stored():
    # most tract ids did not change between 2010 and 2023, so a place lists the same id twice
    rows = [{"place_id": "1", "tract": "48215020100", "share_of_tract": 0.9, "vintage": v} for v in (2010, 2023)]
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection)
        connection.executemany("insert into place_tracts values (:place_id, :tract, :share_of_tract, :vintage)", rows)
        assert connection.execute("select count(*) from place_tracts").fetchone()[0] == 2


def test_small_place_gets_the_tract_covering_most_of_it():
    # a small town is under 20% of every tract around it; it still needs one tract to answer questions
    town = places_frame(("4822576", "Edcouch", "Edcouch city", "C1", box(-98.00, 26.30, -97.99, 26.31)))
    tracts = gpd.GeoDataFrame(
        {"GEOID": ["48215024100", "48215024200"]},
        geometry=[box(-98.10, 26.20, -97.993, 26.40), box(-97.993, 26.20, -97.90, 26.40)],  # 70% / 30% of the town
        crs="EPSG:4326",
    )
    rows = tract_rows(town, tracts, vintage=2023)
    assert [r["tract"] for r in rows] == ["48215024100"]
    assert rows[0]["share_of_tract"] < TRACT_SHARE_MIN  # kept anyway, as the town's main tract
