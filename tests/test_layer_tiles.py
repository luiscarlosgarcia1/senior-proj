"""Pipeline: layer_tiles.py cuts big layers into vector tiles."""

import json
import math

import pytest

pytest.importorskip("pyogrio", reason="needs the pipeline dependency group")

import layer_tiles

SQUARE = json.dumps({"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "properties": {"relative_class": "high", "source": "TWDB"},
    "geometry": {"type": "Polygon", "coordinates": [[
        [-98.25, 26.15], [-98.15, 26.15], [-98.15, 26.25], [-98.25, 26.25], [-98.25, 26.15]]]},
}]})


def _tile_of(lon, lat, z):
    """Standard slippy-map (XYZ) tile numbering."""
    n = 2**z
    lat_rad = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n)


def test_cut_tiles_xyz(tmp_path):
    tiles = layer_tiles.cut_tiles("twdb-test", SQUARE, tmp_path)

    zooms = {z for z, _, _, _ in tiles}
    assert zooms == set(range(layer_tiles.MIN_ZOOM, layer_tiles.MAX_ZOOM + 1))
    assert _tile_of(-98.2, 26.2, 10) == (232, 434)
    assert (10, 232, 434) in {(z, x, y) for z, x, y, _ in tiles}
    assert all(data[:2] == b"\x1f\x8b" for *_, data in tiles)  # gzip-compressed MVT


def test_small_layers_stay_geojson():
    assert layer_tiles.delivery_for(999_999) == "geojson"
    assert layer_tiles.delivery_for(1_000_000) == "geojson"


def test_big_layer_is_tiled():
    assert layer_tiles.delivery_for(1_000_001) == "tiles"


def test_every_layer_row_says_how_it_is_delivered():
    import build_layers
    from database import MapLayer

    row = build_layers._row("fema-nfhl", 0, MapLayer('{"type":"FeatureCollection","features":[]}', 0))

    assert (row["delivery"], row["tiles_hash"]) == ("geojson", None)  # every row has both, so inserts keep them
