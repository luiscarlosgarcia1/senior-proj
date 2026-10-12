"""Pipeline: pipeline/evidence_layers.py — the drainage district's flood photos."""

import json

import pytest

pytest.importorskip("geopandas", reason="needs the pipeline dependency group")

import evidence_layers
import public_sources


def _photo(object_id, lon, lat, **properties):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"OBJECTID": object_id, "Path": "S:\\Flood Events\\IMG.JPG", "Direction": 287.0, **properties},
    }


def test_flood_photos_carry_the_image_address_only_where_one_is_published(monkeypatch):
    monkeypatch.setattr(evidence_layers, "FLOOD_PHOTOS", [("with_images", "September 2018"), ("without", "June 2018")])
    layers = {
        "with_images": [
            _photo(1, -98.2, 26.2, DateTime="2018:09:09 23:25:19"),
            _photo(2, -98.3, 26.3),  # the district attached no image to this one
            _photo(3, -120.0, 45.0),  # a stray GPS tag far outside the valley
        ],
        "without": [_photo(1, -98.1, 26.1, DateTime="2018:06:21 17:56:48")],
    }
    images = {"with_images": {1: "https://example.test/layer/1/attachments/7"}, "without": {}}
    monkeypatch.setattr(evidence_layers, "hcdd1_layer", layers.__getitem__)
    monkeypatch.setattr(evidence_layers, "hcdd1_image_urls", images.__getitem__)

    layer = evidence_layers.build_hcdd1_flood_photos()

    assert layer.feature_count == 3  # the stray one is dropped
    # The one that can be opened comes last, so the map draws it on top. And the
    # district's internal file path and camera heading never leave the pipeline.
    assert [feature["properties"] for feature in json.loads(layer.geojson)["features"]] == [
        {"overlay_type": "flood_photo", "event": "September 2018", "taken": ""},
        {"overlay_type": "flood_photo", "event": "June 2018", "taken": "2018-06-21 17:56"},
        {
            "overlay_type": "flood_photo",
            "event": "September 2018",
            "taken": "2018-09-09 23:25",
            "photo_url": "https://example.test/layer/1/attachments/7",
        },
    ]


def test_image_urls_come_from_the_attachment_listing(tmp_path, monkeypatch):
    pages = [
        {
            "exceededTransferLimit": True,
            "attachmentGroups": [
                {"parentObjectId": 1, "attachmentInfos": [{"id": 7, "contentType": "image/jpeg"}]},
                {"parentObjectId": 2, "attachmentInfos": [{"id": 8, "contentType": "application/pdf"}]},
            ],
        },
        {"attachmentGroups": [{"parentObjectId": 3, "attachmentInfos": [{"id": 9, "contentType": "image/jpeg"}]}]},
    ]
    requested = []

    def fake_get_json(url, **_):
        requested.append(url)
        return pages[len(requested) - 1]

    monkeypatch.setattr(public_sources, "get_json", fake_get_json)
    base = public_sources.hcdd1_layer_url("flood_photos_2018_sept")

    urls = public_sources.hcdd1_image_urls("flood_photos_2018_sept", tmp_path)
    again = public_sources.hcdd1_image_urls("flood_photos_2018_sept", tmp_path)  # read from the cache

    assert urls == again == {1: f"{base}/1/attachments/7", 3: f"{base}/3/attachments/9"}  # the PDF is not a photo
    assert len(requested) == 2 and "resultOffset=2" in requested[1]


def test_a_layer_without_attachments_has_no_image_urls(tmp_path, monkeypatch):
    error = {"error": {"code": 400, "details": ["Layer does not support attachments."]}}
    monkeypatch.setattr(public_sources, "get_json", lambda url, **_: error)

    assert public_sources.hcdd1_image_urls("flood_photos_2018_june", tmp_path) == {}
