"""The app database: the one SQLite file the Flask app reads its map data from.

`build_layers.py` fills `layers`; `build_events.py` fills the other three
tables. Each replaces only its own tables, in one transaction, so either can be
re-run on its own and the app never sees a half-written table. The reading side
is `src/rgv_flood/data_access.py`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import NamedTuple

from paths import APP_DB

# Table name -> the statements that create it (and its indexes).
TABLES: dict[str, tuple[str, ...]] = {
    # One row per map layer: its sidebar/source-card text and the GeoJSON the map draws.
    "layers": (
        """CREATE TABLE IF NOT EXISTS layers (
             id TEXT PRIMARY KEY,
             position INTEGER NOT NULL,            -- order in the sidebar
             title TEXT NOT NULL,
             description TEXT,
             source TEXT,
             vintage TEXT,
             hazard_type TEXT,
             coverage TEXT,
             limitation TEXT,
             source_url TEXT,
             visualizations_json TEXT NOT NULL,    -- [{"title": ..., "url": ...}], the publisher's own maps
             feature_count INTEGER NOT NULL,
             geojson BLOB NOT NULL,                -- UTF-8 FeatureCollection, served to the browser as is
             etag TEXT NOT NULL                    -- changes whenever geojson does
           )""",
    ),
    # Documented flood events (NOAA Storm Events). lon/lat are null when the
    # source gave no usable point; geometry_note says why a given point was dropped.
    "flood_events": (
        """CREATE TABLE IF NOT EXISTS flood_events (
             id TEXT PRIMARY KEY,
             county TEXT NOT NULL,
             date TEXT NOT NULL,
             date_end TEXT,
             type TEXT NOT NULL,
             location TEXT NOT NULL,
             precision TEXT,
             summary TEXT NOT NULL,
             source_url TEXT,
             geometry_note TEXT,
             lon REAL,
             lat REAL
           )""",
        "CREATE INDEX IF NOT EXISTS flood_events_by_county_date ON flood_events(county, date)",
    ),
    # Hand-curated local-news and local-government reports, oldest first.
    "flood_reports": (
        """CREATE TABLE IF NOT EXISTS flood_reports (
             report_id INTEGER PRIMARY KEY,
             county TEXT NOT NULL,
             headline TEXT NOT NULL,
             detail TEXT NOT NULL,
             location TEXT NOT NULL,
             published_at TEXT,
             publisher TEXT NOT NULL,
             channel TEXT NOT NULL,
             source_url TEXT,
             duplicate_group TEXT
           )""",
    ),
    # The wettest single gauge-days on record, wettest first.
    "rainfall_records": (
        """CREATE TABLE IF NOT EXISTS rainfall_records (
             rank INTEGER PRIMARY KEY,
             county TEXT NOT NULL,
             date TEXT NOT NULL,
             mm REAL NOT NULL,
             inches REAL NOT NULL,
             station TEXT NOT NULL
           )""",
    ),
}


class MapLayer(NamedTuple):
    """A built layer: its GeoJSON FeatureCollection as text, and how many features it holds."""

    geojson: str
    feature_count: int


@contextmanager
def open_app_db(path: Path = APP_DB) -> Iterator[sqlite3.Connection]:
    """Open the app database for one all-or-nothing write, creating it if needed.

    Every table always exists afterwards, so the app can query a database that
    only one of the two build scripts has filled so far.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        for statements in TABLES.values():
            for statement in statements:
                connection.execute(statement)
        yield connection


def replace_table(connection: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    """Swap a table's contents for `rows` (dicts keyed by column name).

    The table is dropped and re-created rather than emptied, so a change to its
    definition above takes effect on the next build without a migration.
    """
    connection.execute(f"DROP TABLE IF EXISTS {table}")
    for statement in TABLES[table]:
        connection.execute(statement)
    if rows:
        columns = list(rows[0])
        connection.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})", rows
        )
