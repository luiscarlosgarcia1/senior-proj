"""Vector tiles for the big layers.

A layer whose gzipped GeoJSON is over 1 MB (today the two TWDB modeled-flood
layers) is also cut into Mapbox Vector Tiles, so the browser fetches only the
tiles on screen, simplified to the zoom, instead of the whole file. GDAL (which
pyogrio bundles) writes the tiles into a temporary MBTiles file; they are then
copied into the central database's `layer_tiles` table, in XYZ numbering.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import geopandas as gpd
import pyogrio

TILE_THRESHOLD_BYTES = 1_000_000
MIN_ZOOM = 7  # the map's own minimum: the whole valley on a small screen
MAX_ZOOM = 14  # street level; MapLibre over-zooms past this


def delivery_for(gzipped_size: int) -> str:
    """How the app should send a layer of this compressed size."""
    return "tiles" if gzipped_size > TILE_THRESHOLD_BYTES else "geojson"


def cut_tiles(layer_id: str, geojson: str, workdir: Path) -> list[tuple[int, int, int, bytes]]:
    """(z, x, y, gzipped MVT) for every tile of the layer, zooms MIN_ZOOM..MAX_ZOOM.
    The tiles' one MVT layer is named `layer_id`."""
    frame = gpd.GeoDataFrame.from_features(json.loads(geojson)["features"], crs=4326)
    mbtiles = Path(workdir) / f"{layer_id}.mbtiles"
    mbtiles.unlink(missing_ok=True)
    pyogrio.write_dataframe(
        frame, mbtiles, driver="MBTiles", layer=layer_id,
        dataset_options={"MINZOOM": MIN_ZOOM, "MAXZOOM": MAX_ZOOM},
    )
    with closing(sqlite3.connect(mbtiles)) as connection:
        rows = connection.execute("select zoom_level, tile_column, tile_row, tile_data from tiles").fetchall()
    mbtiles.unlink()
    # MBTiles counts rows from the south (TMS); the web counts from the north (XYZ).
    return [(z, x, 2**z - 1 - row, bytes(data)) for z, x, row, data in rows]
