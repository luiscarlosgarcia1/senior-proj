"""App settings (RGV_* environment) and read-only database access."""

import sqlite3
import sys
from pathlib import Path

import pytest

from rgv_flood.db import Database
from rgv_flood.settings import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("RGV_DATABASE", raising=False)
    settings = Settings()

    assert settings.live_signals_refresh_interval_seconds == 900
    assert settings.live_signals_scheduler_enabled is True
    assert settings.live_signals_scheduler_lock_file == settings.database.parent / ".live-signals-scheduler.lock"
    assert settings.basemap_light_style == "https://tiles.openfreemap.org/styles/positron"
    assert settings.basemap_dark_style == "https://tiles.openfreemap.org/styles/dark"


def test_settings_read_rgv_env(monkeypatch):
    monkeypatch.setenv("RGV_DATABASE", "/x/y.sqlite3")
    monkeypatch.setenv("RGV_LIVE_SIGNALS_SCHEDULER_ENABLED", "false")

    settings = Settings()

    assert settings.database == Path("/x/y.sqlite3")
    assert settings.live_signals_scheduler_enabled is False


def test_database_rows(fixture_db):
    assert Database(fixture_db).rows("select count(*) as n from flood_events")[0]["n"] == 2


def test_database_missing_file(tmp_path):
    database = Database(tmp_path / "not-built.sqlite3")

    assert database.exists is False
    assert database.rows("select 1") is None
    assert database.app_rows("select 1") == []
    assert not (tmp_path / "not-built.sqlite3").exists()  # reading must not create it


def test_database_is_read_only(fixture_db):
    with pytest.raises(sqlite3.OperationalError):
        Database(fixture_db).rows("delete from flood_events")


def test_database_scalar(fixture_db):
    assert Database(fixture_db).scalar("select count(*) from weather_stations") == 3


def _database_with(path: Path, value: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("create table t (n integer)")
        connection.execute("insert into t values (?)", (value,))
    connection.close()


def test_database_keeps_one_connection_per_thread(fixture_db):
    database = Database(fixture_db)
    database.rows("select 1")
    first = database._local.held[1]

    database.rows("select 1")

    assert database._local.held[1] is first


@pytest.mark.skipif(sys.platform == "win32", reason="Windows can't replace a file another connection holds open")
def test_database_reopens_a_replaced_file(tmp_path):
    path = tmp_path / "db.sqlite3"
    _database_with(path, 1)
    database = Database(path)
    assert database.scalar("select n from t") == 1

    _database_with(tmp_path / "rebuilt.sqlite3", 2)
    (tmp_path / "rebuilt.sqlite3").replace(path)

    assert database.scalar("select n from t") == 2
