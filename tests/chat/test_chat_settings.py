"""Chat: the settings that switch it on, and the service built from them."""

import pytest

from rgv_flood.app import create_app
from rgv_flood.chat.agent import AzureModelClient
from rgv_flood.chat.limits import UsageStore
from rgv_flood.chat.service import ChatService
from rgv_flood.settings import Settings, get_settings

AZURE = {
    "azure_openai_endpoint": "https://az.test",
    "azure_openai_api_key": "SECRET-TEST-KEY",
    "azure_openai_deployment": "my-dep",
    "session_secret": "s" * 40,
}
MICROSOFT = {"ms_client_id": "client-id", "ms_client_secret": "CLIENT-SECRET", "ms_tenant_id": "tenant-id", "public_url": "https://site.test"}


def test_chat_is_off_by_default():
    settings = Settings()

    assert settings.chat_enabled is False and settings.login_enabled is False


def test_chat_needs_every_azure_field_and_a_long_session_secret():
    assert Settings(**AZURE).chat_enabled is True
    for missing in AZURE:
        assert Settings(**{k: v for k, v in AZURE.items() if k != missing}).chat_enabled is False, missing
    assert Settings(**{**AZURE, "session_secret": "s" * 31}).chat_enabled is False


def test_login_needs_the_microsoft_fields_and_the_public_address():
    assert Settings(**AZURE).login_enabled is False
    assert Settings(**AZURE, **MICROSOFT).login_enabled is True
    for missing in MICROSOFT:
        assert Settings(**AZURE, **{k: v for k, v in MICROSOFT.items() if k != missing}).login_enabled is False, missing
    assert Settings(**MICROSOFT).login_enabled is False  # no chat, no login


def test_api_version_has_a_default():
    assert Settings().azure_openai_api_version


def test_secrets_are_never_shown(caplog):
    settings = Settings(**AZURE, **MICROSOFT)

    shown = repr(settings) + str(settings) + repr(settings.model_dump())
    for secret in ("SECRET-TEST-KEY", "CLIENT-SECRET", "s" * 40):
        assert secret not in shown
    assert settings.azure_openai_api_key.get_secret_value() == "SECRET-TEST-KEY"


def test_env_file_is_read_by_get_settings_only(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("RGV_AZURE_OPENAI_ENDPOINT=https://from-dotenv.test\n", encoding="utf-8")
    monkeypatch.delenv("RGV_AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        assert get_settings().azure_openai_endpoint == "https://from-dotenv.test"
        assert Settings().azure_openai_endpoint == ""
    finally:
        get_settings.cache_clear()


def test_usage_file_sits_next_to_the_database_by_default(tmp_path):
    assert Settings(database=tmp_path / "x.sqlite3").chat_usage_database == tmp_path / "chat-usage.sqlite3"


def test_create_app_builds_the_service_only_when_chat_is_enabled(fixture_db, tmp_path):
    off = create_app(Settings(database=fixture_db, live_signals_scheduler_enabled=False))
    on = create_app(Settings(database=fixture_db, live_signals_scheduler_enabled=False,
                             chat_usage_database=tmp_path / "usage.sqlite3", **AZURE))

    assert off.state.chat is None
    assert isinstance(on.state.chat, ChatService)
    assert isinstance(on.state.chat.model, AzureModelClient) and isinstance(on.state.chat.usage, UsageStore)
    assert on.state.chat.login is None  # filled in when sign-in is configured (see the Microsoft tests)


@pytest.mark.parametrize("field", ["azure_openai_api_key", "ms_client_secret", "session_secret"])
def test_secret_fields_are_secretstr(field):
    from pydantic import SecretStr

    assert isinstance(getattr(Settings(), field), SecretStr)
