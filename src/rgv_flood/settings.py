"""The app's settings, read from RGV_* environment variables.

Every setting has an RGV_ prefix and a default that works for local development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RGV_")

    database: Path = REPO_ROOT / "data" / "generated" / "rgv-flood.sqlite3"
    live_signals_scheduler_enabled: bool = True
    live_signals_refresh_interval_seconds: int = 900
    # Defaults to a file next to the database (see below).
    live_signals_scheduler_lock_file: Path | None = None
    basemap_light_style: str = "https://tiles.openfreemap.org/styles/positron"
    basemap_dark_style: str = "https://tiles.openfreemap.org/styles/dark"
    geocoder_url: str = "https://nominatim.openstreetmap.org/search"
    # Nominatim's usage policy asks every client to identify itself.
    geocoder_user_agent: str = "RGV-Flood-Impact-Visualizer/1.0 (UTRGV senior project)"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _lock_file_next_to_database(self) -> Settings:
        if self.live_signals_scheduler_lock_file is None:
            self.live_signals_scheduler_lock_file = self.database.parent / ".live-signals-scheduler.lock"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
