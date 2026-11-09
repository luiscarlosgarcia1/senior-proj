"""The JSON API, under /api/v1. Every endpoint is a GET that only reads, except the chat, a POST that also only reads the data."""

from __future__ import annotations

from fastapi import APIRouter

from rgv_flood.api import (
    chat,
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
for module in (layers, tiles, events, panels, news, live_signals, history, trends, chat, geocode):
    api_router.include_router(module.router)
