"""Response models for every API endpoint. They are what /docs shows and what
the tests check the responses against."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    built_at: str | None = None


# ---- layers ----


class Link(BaseModel):
    title: str
    url: str


class Legend(BaseModel):
    shape: str
    color: str


class LayerPart(BaseModel):
    id: str
    label: str
    filter: list  # a MapLibre filter expression


class LayerInfo(BaseModel):
    id: str
    title: str
    short_label: str
    row_label: str
    panel_row: str
    feature_count: int
    legend: Legend
    parts: list[LayerPart] = []
    delivery: Literal["geojson", "tiles", "api"]
    url: str
    description: str | None = None
    source: str | None = None
    vintage: str | None = None
    hazard_type: str | None = None
    coverage: str | None = None
    limitation: str | None = None
    source_url: str | None = None
    visualizations: list[Link] = []


class LayerGroup(BaseModel):
    id: str
    title: str
    layers: list[LayerInfo]


class LayersResponse(BaseModel):
    base: list[LayerInfo]
    groups: list[LayerGroup]


# ---- events, rainfall, reports ----


class Event(BaseModel):
    id: str
    county: str
    date: str
    date_end: str | None = None
    type: str
    location: str | None = None
    precision: str | None = None
    summary: str | None = None
    source_url: str | None = None
    geometry_note: str | None = None
    lon: float | None = None
    lat: float | None = None


class EventsResponse(BaseModel):
    total: int
    years: list[int]
    types: list[str]
    events: list[Event]


class RainDay(BaseModel):
    date: str
    label: str
    began: bool


class GaugeRain(BaseModel):
    name: str
    distance_km: float | None = None
    inches: list[float | None]


class RainNearEvent(BaseModel):
    days: list[RainDay]
    gauges: list[GaugeRain]
    located: bool


class Report(BaseModel):
    id: str
    county: str
    headline: str
    detail: str | None = None
    location: str | None = None
    location_precision: str | None = None
    event_date: str
    event_end: str | None = None
    published_at: str | None = None
    publisher: str | None = None
    channel: str | None = None
    source_url: str | None = None
    duplicate_group: str | None = None


class NwsReport(BaseModel):
    id: str
    county: str
    kind: str
    reported_at: str
    city: str | None = None
    remark: str | None = None
    source: str | None = None
    magnitude: float | None = None
    lon: float | None = None
    lat: float | None = None


class EventContext(BaseModel):
    event: Event
    rain: RainNearEvent
    reports: list[Report]
    nws_reports: list[NwsReport]


class RainfallRecord(BaseModel):
    county: str
    date: str
    station: str
    mm: float
    inches: float


# Query parameter type: one of the four counties (anything else is a 422).
County = Literal["cameron", "hidalgo", "starr", "willacy"]
