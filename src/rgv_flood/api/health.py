"""/health: what Docker and Caddy poll."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rgv_flood.api.models import HealthResponse
from rgv_flood.db import Database, Db

router = APIRouter()


def built_at(db: Database) -> str | None:
    """When the pipeline last built the database (None if unknown)."""
    try:
        return db.scalar("select value from build_info where key = 'built_at'")
    except sqlite3.OperationalError:  # a database built before build_info existed
        return None


@router.get("/health", response_model=HealthResponse)
def health(db: Db):
    if not db.exists:
        return JSONResponse({"status": "unavailable", "database": "missing", "built_at": None}, status_code=503)
    try:
        db.scalar("select 1")
    except sqlite3.Error:
        return JSONResponse({"status": "unavailable", "database": "unreadable", "built_at": None}, status_code=503)
    return HealthResponse(status="ok", database="ok", built_at=built_at(db))
