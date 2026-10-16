"""Shared fixtures. The fixture database itself is built by `fixture_db.py`."""

import pytest
from fixture_db import build_fixture_database


@pytest.fixture()
def fixture_db(tmp_path):
    """A small built database (events, gauges, reports, sources, claims history)."""
    return build_fixture_database(tmp_path / "rgv-flood.sqlite3", history=True)
