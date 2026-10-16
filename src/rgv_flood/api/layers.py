"""/api/v1/layers: the layer panel's contents, and each small layer's GeoJSON."""

from __future__ import annotations

import gzip

from fastapi import APIRouter, HTTPException, Request, Response

from rgv_flood import data_access
from rgv_flood.api.models import LayerGroup, LayerInfo, LayersResponse
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db
from rgv_flood.i18n import t

router = APIRouter()

GROUP_ORDER = ("hazard", "works", "evidence", "projects")
LAYER_CACHE = "public, max-age=300, stale-while-revalidate=86400"


def _virtual_layers() -> list[LayerInfo]:
    """Rows in the panel whose data comes from the API rather than a built layer:
    NOAA's flood events and the live official alerts."""

    def virtual(layer_id: str, key: str, url: str, shape: str, color: str) -> LayerInfo:
        title = t(f"layers.virtual.{key}.title")
        return LayerInfo(
            id=layer_id, title=title, short_label=title, row_label=title, panel_row=layer_id, feature_count=0,
            legend={"shape": shape, "color": color}, delivery="api", url=url,
            source=t(f"layers.virtual.{key}.source"),
        )

    return [
        virtual("noaa-flood-events", "events", "/api/v1/events.geojson", "dot", "sev-high"),
        virtual("live-alerts", "alerts", "/api/v1/live-signals.geojson", "dia", "warn"),
    ]


def _info(row: dict) -> LayerInfo:
    if row["delivery"] == "tiles":
        url = f"/api/v1/tiles/{row['id']}/{{z}}/{{x}}/{{y}}.pbf?v={row['tiles_hash']}"
    else:
        url = f"/api/v1/layers/{row['id']}.geojson"
    return LayerInfo(**row, url=url)


@router.get("/layers", response_model=LayersResponse)
def layers(request: Request, db: Db):
    rows = data_access.available_layers(db)
    if not rows:
        return conditional_json(request, LayersResponse(base=[], groups=[]), max_age=60)
    by_group: dict[str, list[LayerInfo]] = {}
    for row in rows:
        by_group.setdefault(row["layer_group"], []).append(_info(row))
    by_group.setdefault("evidence", []).extend(_virtual_layers())
    groups = [
        LayerGroup(id=group, title=t(f"layers.group.{group}"), layers=by_group[group])
        for group in GROUP_ORDER if by_group.get(group)
    ]
    return conditional_json(request, LayersResponse(base=by_group.get("base", []), groups=groups), max_age=60)


@router.get("/layers/{layer_id}.geojson")
def layer_geojson(layer_id: str, request: Request, db: Db):
    """The layer's GeoJSON as the pipeline built it: stored gzipped and sent that
    way to any browser that accepts it (all of them); a browser that already has
    this version gets a 304 without the geometry being read at all."""
    layer = data_access.layer_geojson_gzip(db, layer_id, request.headers.get("if-none-match", ""))
    if layer is None:
        raise HTTPException(404, "No such layer")
    headers = {"ETag": f'"{layer["etag"]}"', "Cache-Control": LAYER_CACHE, "Vary": "Accept-Encoding"}
    body = layer["body"]
    if body is None:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(body, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(gzip.decompress(body), media_type="application/json", headers=headers)
