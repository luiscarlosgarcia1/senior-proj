"""/api/v1/trends: time series of rain, flood events, NWS reports and news, by year and month."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, Trends
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()


@router.get("/trends", response_model=Trends)
def trends(request: Request, db: Db, county: County | None = None, station: str | None = None):
    last_year = datetime.now(UTC).year - 1  # the current year isn't over
    try:
        body = Trends(**data_access.trends(db, county, station, last_year))
    except data_access.UnknownStation:
        raise HTTPException(404, "No such gauge in that county") from None
    return conditional_json(request, body, max_age=300)
