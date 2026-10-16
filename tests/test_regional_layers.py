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


def test_flood_infrastructure_keeps_flood_works_and_names_coastal_ones():
    def infrastructure(infra_type, description):
        return regional_layers._infrastructure({"INFRA_TYPE": infra_type, "DESCR": description, "NAME": "X"})

    assert infrastructure("Dam", "River: Arroyo Colorado")["kind"] == "dam"
    assert infrastructure("Other", "Beach Nourishment Project - 4000 Cubic Yards")["kind"] == "coastal"
    assert infrastructure("Other", "Jetty")["kind"] == "coastal"
    assert infrastructure("Other", "System Unit")["kind"] == "other"
    assert infrastructure("Other", "Otherwise Protected Area") is None  # land set aside, not a flood work


def test_overture_adds_only_named_dams_the_state_lacks(monkeypatch):
    from shapely.geometry import Point

    polygons = {"hidalgo": box(-98.5, 26.0, -98.0, 26.5)}
    monkeypatch.setattr(regional_layers.overture, "bridges_and_dams", lambda: iter([
        (Point(-98.2, 26.2), {"class": "dam", "names": {"primary": "Same Dam, Drawn Again"}}),  # ~100 m from the state's
        (Point(-98.4, 26.1), {"class": "dam", "names": {"primary": "Retamal Diversion Dam"}}),
        (Point(-98.3, 26.3), {"class": "dam", "names": None}),  # unnamed: can't be checked
        (Point(-98.1, 26.4), {"class": "bridge", "names": {"primary": "A Bridge"}}),
    ]))

    added = regional_layers._dams_the_state_lacks([Point(-98.201, 26.2)], polygons)

    assert [(f["properties"]["name"], f["properties"]["source"]) for f in added] == [
        ("Retamal Diversion Dam", "Overture Maps Foundation"),
    ]


def test_census_line_along_a_local_ditch_is_left_to_the_local_layer():
    local = LineString([(0, 0), (0.1, 0)]).buffer(regional_layers.NEAR_DEGREES)

    assert regional_layers._mapped_locally(LineString([(0, 0.0003), (0.1, 0.0003)]), local)  # runs alongside
    assert not regional_layers._mapped_locally(LineString([(0, 0), (0, 0.1)]), local)  # crosses it


def _commons_photo(title, caption, **values):
    return {"title": title, "caption": caption, "artist": "Jacinta Quesada", "taken": "2008-07-25",
            "page_url": f"https://commons.example/{title}", "thumb_url": f"https://thumb.example/{title}", **values}


def test_fema_photos_of_flooding_are_grouped_by_the_town_their_caption_names(monkeypatch):
    from shapely.geometry import Point

    photos = [
        _commons_photo("File:FEMA - 37265 - Flooded neighborhood in Texas.jpg",
                       "Raymondville, TX, July 25, 2008 -- Flood waters remain in some neighborhoods."),
        _commons_photo("File:FEMA - 37215 - Cars travel through flooded Welasco,Texas streets.jpg",
                       "Welasco,TX, July 24, 2008 -- Local residents attempt to navigate the streets."),
        # mentions the flood, but shows a relief line
        _commons_photo("File:FEMA - 37415 - Red Cross volunteer gives snacks to children in Texas.jpg",
                       "Edinburg, TX, July 31, 2008 -- A Red Cross volunteer gives snacks. Her house was flooded."),
        # shows flooding, but no town to place it at
        _commons_photo("File:FEMA - 37305 - Aerial of a flooded neighborhood in Texas.jpg",
                       "undetermined, TX, July 25, 2008 -- A flooded neighborhood in Texas."),
    ]
    monkeypatch.setattr(regional_layers, "commons_flood_photos", lambda: photos)
    monkeypatch.setattr(regional_layers, "_places", lambda: {
        "Raymondville": Point(-97.78, 26.48), "Weslaco": Point(-97.99, 26.16), "Edinburg": Point(-98.16, 26.32)})
    monkeypatch.setattr(regional_layers, "_county_polygons", lambda: {
        "willacy": box(-98.0, 26.4, -97.3, 26.6), "hidalgo": box(-98.6, 26.0, -97.9, 26.4)})

    layer = regional_layers.build_fema_flood_photos()

    towns = {f["properties"]["town"]: f for f in json.loads(layer.geojson)["features"]}
    assert set(towns) == {"Raymondville", "Weslaco"}  # "Welasco" is FEMA's misspelling
    assert towns["Raymondville"]["geometry"]["coordinates"] == [-97.78, 26.48]
    assert towns["Raymondville"]["properties"]["county"] == "Willacy"
    (photo,) = towns["Weslaco"]["properties"]["photos"]
    assert photo["credit"] == "Jacinta Quesada"
    assert photo["page_url"].endswith("Cars travel through flooded Welasco,Texas streets.jpg")
