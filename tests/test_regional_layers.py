"""Pipeline: pipeline/regional_layers.py — the layers that cover all four counties."""

import json

import pytest

pytest.importorskip("geopandas", reason="needs the pipeline dependency group")

import regional_layers
from database import open_database, replace_table
from shapely.geometry import LineString, box


@pytest.mark.parametrize(
    ("mtfcc", "name", "kind"),
    [
        ("H3020", "West Main Drn", "drain"),
        ("H3020", "North Floodway", "drain"),
        ("H3020", "Edinburg Main Cnl", "canal"),
        ("H3020", "Resaca de la Guerra", "resaca"),
        ("H3020", None, "canal_or_ditch"),
        ("H3010", "Garcias Crk", "creek"),
        ("H3010", "Town Resaca", "resaca"),
        ("H1100", "Laguna Madre", None),  # a connector, not drawn
    ],
)
def test_waterway_kind_comes_from_the_census_class_and_the_name(mtfcc, name, kind):
    assert regional_layers._waterway_kind(mtfcc, name) == kind


def test_ditch_owner_codes_are_spelled_out_only_when_certain():
    assert regional_layers._owner("CCDD5") == "Cameron County Drainage District No. 5"
    assert regional_layers._owner("COH") == "City of Harlingen"
    assert regional_layers._owner("HID") == "HID"  # not certain what it stands for: shown as published
    assert regional_layers._ditch_name("Unknown", "CC") is None
    assert regional_layers._ditch_name("CCDD3", "CCDD3") is None
    assert regional_layers._ditch_name("North Main Drain", "CCDD5") == "North Main Drain"


def test_a_feature_belongs_to_the_county_holding_its_middle():
    polygons = {"cameron": box(0, 0, 10, 10), "willacy": box(10, 0, 20, 10)}

    assert regional_layers._county_of(box(8, 2, 18, 8), polygons) == "willacy"  # not the alphabetically first
    assert regional_layers._county_of(LineString([(9, 5), (13, 5), (14, 5), (19, 5)]), polygons) == "willacy"
    assert regional_layers._county_of(LineString([(30, 5), (40, 5)]), polygons) is None


def test_nws_flood_reports_layer_is_built_from_the_database(tmp_path):
    database = tmp_path / "db.sqlite3"
    assert regional_layers.build_nws_flood_reports(database) is None  # nothing built yet
    with open_database(database) as connection:
        replace_table(connection, "nws_flood_reports", [{
            "id": "r1", "county": "starr", "kind": "flash_flood", "reported_at": "2007-06-23T00:08:00Z",
            "city": "Roma", "remark": "Numerous streets impassable.", "source": "Public", "magnitude": None,
            "lon": -99.0, "lat": 26.41,
        }])

    layer = regional_layers.build_nws_flood_reports(database)

    (feature,) = json.loads(layer.geojson)["features"]
    assert feature["geometry"]["coordinates"] == [-99.0, 26.41]
    assert feature["properties"] == {
        "overlay_type": "storm_report", "kind": "flash_flood", "reported_at": "2007-06-23T00:08:00Z",
        "city": "Roma", "remark": "Numerous streets impassable.", "source": "Public", "county": "Starr",
    }
