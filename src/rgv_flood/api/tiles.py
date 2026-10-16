"""/api/v1/tiles: vector tiles of the big layers.

A tile's URL carries the layer's build hash (from /layers), so a tile never
changes at its address and browsers and proxies may keep it for a year.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response

from rgv_flood import data_access
from rgv_flood.db import Db

router = APIRouter()

TILE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/tiles/{layer_id}/{z}/{x}/{y}.pbf")
def tile(layer_id: str, z: Annotated[int, Path(ge=0, le=22)], x: int, y: int, db: Db):
    if not (0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(422, "Tile x and y must be within 0 .. 2^z - 1")
    tile = data_access.layer_tile(db, layer_id, z, x, y)
    if tile is None:
        raise HTTPException(404, "No tiles for this layer")
    data = tile["data"]
    if data is None:
        return Response(status_code=204, headers=TILE_HEADERS)  # MapLibre reads this as an empty tile
    return Response(
        data, media_type="application/vnd.mapbox-vector-tile", headers={**TILE_HEADERS, "Content-Encoding": "gzip"}
    )
