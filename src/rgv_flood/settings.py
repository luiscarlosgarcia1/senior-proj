"""The app's settings, read from RGV_* environment variables.

Every setting has an RGV_ prefix and a default that works for local development.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rgv_flood.chat.keyfile import KeyFileError, read_key_file

REPO_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)
SESSION_SECRET_MIN = 32


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

    # The data chatbot. Secrets are SecretStr, so they never appear in a repr or a dump.
    # Chat switches on only when the Azure settings and a long session secret are all present.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    # Instead of putting the key in the environment, point at a file that holds it (RTF or plain text).
    # A relative path is from the repository root. A key in the environment wins over the file. If the
    # file holds several values, `..._label` is the text before the colon on the right line.
    azure_openai_api_key_file: Path | None = None
    azure_openai_api_key_label: str = ""
    # Sign in with a UTRGV Microsoft account (see the README for the app registration).
    ms_client_id: str = ""
    ms_client_secret: SecretStr = SecretStr("")
    ms_tenant_id: str = ""  # UTRGV's tenant, used to check who signed in
    public_url: str = ""  # the site's own https address, for the sign-in return address
    session_secret: SecretStr = SecretStr("")  # signs the chat cookies; at least 32 characters
    # Daily message counts; defaults to a file next to the database (see below).
    chat_usage_database: Path | None = None

    @property
    def chat_enabled(self) -> bool:
        return bool(
            self.azure_openai_endpoint and self.azure_openai_deployment
            and self.azure_openai_api_key.get_secret_value()
            and len(self.session_secret.get_secret_value()) >= SESSION_SECRET_MIN
        )

    @property
    def login_enabled(self) -> bool:
        return bool(
            self.chat_enabled and self.ms_client_id and self.ms_tenant_id and self.public_url
            and self.ms_client_secret.get_secret_value()
        )

    @model_validator(mode="after")
    def _key_from_file(self) -> Settings:
        if self.azure_openai_api_key.get_secret_value() or self.azure_openai_api_key_file is None:
            return self
        path = Path(self.azure_openai_api_key_file)
        path = path if path.is_absolute() else REPO_ROOT / path
        try:
            self.azure_openai_api_key = SecretStr(read_key_file(path, self.azure_openai_api_key_label))
        except KeyFileError as error:  # the chat stays off; the rest of the site is unaffected
            logger.warning("Azure key file not used: %s", error)
        return self

    @model_validator(mode="after")
    def _lock_file_next_to_database(self) -> Settings:
        if self.live_signals_scheduler_lock_file is None:
            self.live_signals_scheduler_lock_file = self.database.parent / ".live-signals-scheduler.lock"
        if self.chat_usage_database is None:
            self.chat_usage_database = self.database.parent / "chat-usage.sqlite3"
        return self


@lru_cache
def get_settings() -> Settings:
    # A local `.env` (gitignored) is read by the running app only, not by tests that build Settings() directly.
    return Settings(_env_file=".env")
