"""/api/v1/news: water-related news stories and official announcements, linked to the publisher."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, NewsArticle
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()
MAX_AGE = 60


@router.get("/news", response_model=list[NewsArticle])
def news(
    request: Request,
    db: Db,
    county: County | None = None,
    year: Annotated[int | None, Query(ge=1990, le=2100)] = None,
    topic: Literal["flood", "rain", "storm", "drought", "water_system", "water"] | None = None,
    kind: Literal["news", "official"] | None = None,
):
    rows = data_access.news_articles(db, county, year, topic, kind)
    return conditional_json(request, [NewsArticle(**row) for row in rows], MAX_AGE)
