"""Shared fixtures. The fixture database itself is built by `fixture_db.py`."""

import pytest
from fixture_db import build_fixture_database


@pytest.fixture()
def fixture_db(tmp_path):
    """A small built database (events, gauges, reports, sources, claims history)."""
    return build_fixture_database(tmp_path / "rgv-flood.sqlite3", history=True)


@pytest.fixture()
def make_client():
    """Build a TestClient for an app on the given database (scheduler off)."""
    from fastapi.testclient import TestClient

    from rgv_flood.app import create_app
    from rgv_flood.settings import Settings

    clients = []

    def make(database, **settings):
        client = TestClient(create_app(Settings(database=database, live_signals_scheduler_enabled=False, **settings)))
        clients.append(client.__enter__())
        return clients[-1]

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture()
def api_client(make_client, fixture_db):
    return make_client(fixture_db)
