"""Read-only historic publisher-news evidence for the optional map layer."""

from __future__ import annotations

from fastapi import APIRouter, Request

from rgv_flood import data_access
from rgv_flood.api.models import County
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()
MAX_AGE = 60


@router.get("/historic-news.geojson")
def historic_news_geojson(request: Request, db: Db, county: County | None = None):
    """Only authorized historic reporting points; no live or official signals."""
    return conditional_json(request, data_access.historic_news_features(db, county), MAX_AGE)
