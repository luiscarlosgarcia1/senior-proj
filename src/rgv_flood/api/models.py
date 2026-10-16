"""Response models for every API endpoint. They are what /docs shows and what
the tests check the responses against."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    built_at: str | None = None
