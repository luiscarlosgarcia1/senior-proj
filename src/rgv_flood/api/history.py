"""/api/v1/history: flood-insurance claims beside rainfall, year by year."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, History
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()


@router.get("/history", response_model=History)
def history(request: Request, db: Db, county: County | None = None):
    last_year = datetime.now(UTC).year - 1  # the current year isn't over
    body = History(
        first_year=data_access.HISTORY_FIRST_YEAR,
        last_year=last_year,
        **data_access.history_by_year(db, county, last_year),
    )
    return conditional_json(request, body, max_age=300)
