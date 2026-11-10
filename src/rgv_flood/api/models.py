"""Response models for every API endpoint. They are what /docs shows and what
the tests check the responses against."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


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
    color: str | None = None  # its dot's color key, when it differs from the layer's


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


class OtherOutlet(BaseModel):
    """Another outlet that told the same story (a copy cleaning merged into this one)."""

    publisher: str
    source_url: str


class NewsArticle(BaseModel):
    id: str
    publisher: str
    source_url: str
    headline: str
    published_at: str
    excerpt: str | None = None
    county: str | None = None
    counties: list[str]
    city: str | None = None
    places: str | None = None
    topics: list[str] = []
    kind: str = "news"
    headline_from: str = "page"
    also_reported_by: list[OtherOutlet] = []


class EventContext(BaseModel):
    event: Event
    rain: RainNearEvent
    reports: list[Report]
    nws_reports: list[NwsReport]
    news: list[NewsArticle]


class RainfallRecord(BaseModel):
    county: str
    date: str
    station: str
    mm: float
    inches: float


# Query parameter type: one of the four counties (anything else is a 422).
County = Literal["cameron", "hidalgo", "starr", "willacy"]


# ---- live signals ----


class LiveSignal(BaseModel):
    source: str
    native_id: str
    source_url: str
    source_publisher: str
    source_channel: str
    summary: str
    county_slugs: list[str]
    is_mappable: bool
    geometry_absence_reason: str | None = None
    published_at: str | None = None
    effective_at: str | None = None
    source_updated_at: str | None = None
    expires_at: str | None = None
    last_seen_at: str
    retrieved_at: str


class LiveSignalsResponse(BaseModel):
    refreshed_at: str | None
    signals: list[LiveSignal]


# ---- claims history ----


class HistoryYear(BaseModel):
    year: int
    claims: int
    paid: int
    flood_event: str | None = None
    policies: int | None = None
    claims_per_1000_policies: float | None = None
    rain_inches: float | None = None
    complete_gauges: int
    wettest_day_inches: float | None = None


class HistoryTotals(BaseModel):
    claims: int
    paid: int
    worst_year: int | None = None
    worst_year_claims: int
    worst_year_event: str | None = None


class Correlation(BaseModel):
    years: int
    with_annual_rain: float | None = None
    with_wettest_day: float | None = None


class History(BaseModel):
    first_year: int
    last_year: int
    years: list[HistoryYear]
    totals: HistoryTotals
    correlation: Correlation


# ---- trends ----


class TrendStation(BaseModel):
    station_id: str
    name: str
    county: str


class RainYear(BaseModel):
    year: int
    inches: float | None = None
    wettest_day_inches: float | None = None
    days_over_2_inches: float | None = None
    complete: bool


class RainMonth(BaseModel):
    year: int
    month: int
    inches: float | None = None
    days_reported: int


class EventYear(BaseModel):
    year: int
    total: int
    by_type: dict[str, int]


class NwsYear(BaseModel):
    year: int
    total: int
    by_kind: dict[str, int]


class NewsYear(BaseModel):
    year: int
    count: int


class Trends(BaseModel):
    stations: list[TrendStation]
    station: str | None = None
    rain_years: list[RainYear]
    rain_months: list[RainMonth]
    events_by_year: list[EventYear]
    nws_by_year: list[NwsYear]
    news_by_year: list[NewsYear]
    news_first_year: int | None = None


# ---- sources ----


class Source(BaseModel):
    id: str
    publisher: str | None = None
    dataset: str | None = None
    url: str | None = None
    retrieved_at: str | None = None
    record_count: int | None = None
    notes: str | None = None


class SourcesResponse(BaseModel):
    built_at: str | None
    sources: list[Source]


# ---- address search ----


class Place(BaseModel):
    label: str
    lon: float
    lat: float


# ---- chat ----


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    history: Annotated[list[ChatTurn], Field(max_length=10)] = []


class ChatResponse(BaseModel):
    answer: str
    remaining: int | None
    limit: int | None
    signed_in: bool


class ChatStatus(BaseModel):
    enabled: bool
    login_enabled: bool
    signed_in: bool
    email: str | None = None
    remaining: int | None = None
    limit: int | None = None


# ---- what the news archive says ----


class NewsMonth(BaseModel):
    month: str  # YYYY-MM
    stories: int  # flood, rain and storm stories
    rain_inches: float | None = None  # the gauges' average, None when no gauge reported most of the month
    nws_reports: int
    claims: int


class NewsCorrelation(BaseModel):
    months: int
    rain_months: int
    rain: float | None = None  # Spearman's rank correlation, -1 to 1
    rain_next_month: float | None = None  # rain in one month against the next month's stories
    nws: float | None = None
    claims: float | None = None


class NewsDay(BaseModel):
    date: str
    stories: int
    outlets: int
    headline: str
    source_url: str


class CountyCoverage(BaseModel):
    county: str
    stories: int
    claims: int
    nws_reports: int
    stories_per_100_claims: float | None = None
    stories_per_nws_report: float | None = None


class RecurringPlace(BaseModel):
    name: str
    stories: int
    first: str
    last: str
    latest_headline: str
    latest_url: str


class WaterProblemTown(BaseModel):
    city: str
    county: str | None = None
    stories: int
    first: str
    last: str
    latest_headline: str
    latest_url: str


class NewsLanguages(BaseModel):
    spanish: int
    english: int


class NewsInsights(BaseModel):
    first_year: int
    months: list[NewsMonth]
    correlation: NewsCorrelation | None = None
    wet_quiet: list[NewsMonth]
    loud_dry: list[NewsMonth]
    busiest_days: list[NewsDay]
    coverage: list[CountyCoverage]
    places: list[RecurringPlace]
    water_systems: list[WaterProblemTown]
    languages: NewsLanguages


class NewsTimelineDay(BaseModel):
    date: str
    stories: list[NewsArticle]
