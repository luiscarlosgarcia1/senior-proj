"""/api/v1/news: water-related news stories and official announcements, linked to the publisher."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, NewsArticle, NewsInsights, NewsTimelineDay
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


@router.get("/news/insights", response_model=NewsInsights)
def news_insights(request: Request, db: Db, county: County | None = None):
    """What the news archive shows from 2017 through last month, set against rain, NWS reports and claims."""
    first_of_month = datetime.now(UTC).date().replace(day=1)
    body = NewsInsights(**data_access.news_insights(db, county, first_of_month - timedelta(days=1)))
    return conditional_json(request, body, 300)


@router.get("/news/timeline", response_model=list[NewsTimelineDay])
def news_timeline(request: Request, db: Db, start: date, end: date, county: County | None = None):
    """Every day from `start` to `end` (at most a month) with the stories published that day."""
    if end < start or (end - start).days >= data_access.TIMELINE_MAX_DAYS:
        raise HTTPException(422, f"end must be on or after start, and at most {data_access.TIMELINE_MAX_DAYS} days later")
    days = data_access.news_timeline(db, start, end, county)
    return conditional_json(request, [NewsTimelineDay(**day) for day in days], MAX_AGE)
