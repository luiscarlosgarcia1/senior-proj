"""/api/v1 side-panel data: rainfall records and curated local reports."""

from __future__ import annotations

from fastapi import APIRouter, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, RainfallRecord, Report, Source, SourcesResponse
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()
MAX_AGE = 60


@router.get("/rainfall-records", response_model=list[RainfallRecord])
def rainfall_records(request: Request, db: Db, county: County | None = None):
    rows = data_access.rainfall_records(db, county)
    return conditional_json(request, [RainfallRecord(**row) for row in rows], MAX_AGE)


@router.get("/reports", response_model=list[Report])
def reports(request: Request, db: Db, county: County | None = None):
    return conditional_json(request, [Report(**row) for row in data_access.flood_reports(db, county)], MAX_AGE)


@router.get("/sources", response_model=SourcesResponse)
def sources(request: Request, db: Db):
    body = SourcesResponse(
        built_at=data_access.built_at(db) if db.exists else None,
        sources=[Source(**row) for row in data_access.data_sources(db)],
    )
    return conditional_json(request, body, MAX_AGE)
