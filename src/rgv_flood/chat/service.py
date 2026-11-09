"""The chat feature's parts, built once from the settings and kept on `app.state.chat`.

Tests replace `model` with a scripted fake; nothing here calls Azure until a
request arrives and a real `AzureModelClient` is asked for an answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from rgv_flood.chat.agent import AzureModelClient, ModelClient
from rgv_flood.chat.limits import UsageStore
from rgv_flood.chat.microsoft import MicrosoftLogin
from rgv_flood.db import Database
from rgv_flood.settings import Settings


@dataclass
class ChatService:
    settings: Settings
    db: Database
    model: ModelClient
    usage: UsageStore
    login: MicrosoftLogin | None = None  # set when sign-in is configured

    @classmethod
    def from_settings(cls, settings: Settings, db: Database) -> ChatService:
        model = AzureModelClient(
            settings.azure_openai_endpoint,
            settings.azure_openai_api_key.get_secret_value(),
            settings.azure_openai_deployment,
            settings.azure_openai_api_version,
        )
        usage = UsageStore(settings.chat_usage_database, pepper=settings.session_secret.get_secret_value())
        login = MicrosoftLogin(settings) if settings.login_enabled else None
        return cls(settings=settings, db=db, model=model, usage=usage, login=login)
