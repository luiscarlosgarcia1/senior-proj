"""/api/v1/live-signals: current official alerts, road closures and notices,
as the background refresher last stored them."""

from __future__ import annotations

from fastapi import APIRouter, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, LiveSignal, LiveSignalsResponse
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()
MAX_AGE = 30  # the refresher polls every 15 minutes; keep the panel close behind it


@router.get("/live-signals", response_model=LiveSignalsResponse)
def live_signals(request: Request, db: Db, county: County | None = None):
    body = LiveSignalsResponse(
        refreshed_at=data_access.live_signals_refreshed_at(db) if db.exists else None,
        signals=[LiveSignal(**row) for row in data_access.active_official_signals(db, county)],
    )
    return conditional_json(request, body, MAX_AGE)


@router.get("/live-signals.geojson")
def live_signals_geojson(request: Request, db: Db):
    collection = data_access.active_official_signal_features(db) or {"type": "FeatureCollection", "features": []}
    return conditional_json(request, collection, MAX_AGE)
