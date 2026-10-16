"""The JSON API, under /api/v1. Every endpoint is a read-only GET."""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
