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
