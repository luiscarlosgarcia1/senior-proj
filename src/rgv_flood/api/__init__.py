"""The JSON API, under /api/v1. Every endpoint is a read-only GET."""

from __future__ import annotations

from fastapi import APIRouter

from rgv_flood.api import events, history, layers, live_signals, panels, tiles

api_router = APIRouter(prefix="/api/v1")
for module in (layers, tiles, events, panels, live_signals, history):
    api_router.include_router(module.router)
