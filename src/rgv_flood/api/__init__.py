"""The JSON API, under /api/v1. Every endpoint is a read-only GET."""

from __future__ import annotations

from fastapi import APIRouter

from rgv_flood.api import (
    events,
    geocode,
    history,
    layers,
    live_signals,
    news,
    panels,
    tiles,
    trends,
)

api_router = APIRouter(prefix="/api/v1")
for module in (layers, tiles, events, panels, news, live_signals, history, trends, geocode):
    api_router.include_router(module.router)
