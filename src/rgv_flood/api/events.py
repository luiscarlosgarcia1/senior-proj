"""/api/v1/events: NOAA's flood events, and what else is known about one."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from rgv_flood import data_access
from rgv_flood.api.models import County, Event, EventContext, EventsResponse
from rgv_flood.caching import conditional_json
from rgv_flood.db import Db

router = APIRouter()
MAX_AGE = 60


@router.get("/events", response_model=EventsResponse)
def events(
    request: Request,
    db: Db,
    county: County | None = None,
    type: str | None = None,
    year: Annotated[int | None, Query(ge=1950, le=2100)] = None,
):
    rows = data_access.flood_events(db, str(year) if year else None, county, type)
    body = EventsResponse(
        total=data_access.flood_event_count(db),
        years=[int(y) for y in data_access.flood_event_years(db, county)],
        types=data_access.flood_event_types(db, county),
        events=[Event(**row) for row in rows],
    )
    return conditional_json(request, body, MAX_AGE)


@router.get("/events.geojson")
def events_geojson(request: Request, db: Db, county: County | None = None):
    """The events the map can plot (those with a point), as GeoJSON."""
    collection = data_access.flood_events_geojson(db) or {"type": "FeatureCollection", "features": []}
    features = [
        f for f in collection["features"]
        if f["geometry"] is not None and (county is None or f["properties"]["county"] == county)
    ]
    return conditional_json(request, {"type": "FeatureCollection", "features": features}, MAX_AGE)


@router.get("/events/{event_id}/context", response_model=EventContext)
def event_context(event_id: str, request: Request, db: Db):
    event = data_access.flood_event(db, event_id)
    if event is None:
        raise HTTPException(404, "No such event")
    body = EventContext(
        event=Event(**event),
        rain=data_access.rainfall_near_event(db, event),
        reports=data_access.reports_near_event(db, event),
        nws_reports=data_access.nws_reports_near_event(db, event),
        news=data_access.news_near_event(db, event),
    )
    return conditional_json(request, body, MAX_AGE)
