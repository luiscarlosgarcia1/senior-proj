"""The central database: every table the project has, defined in one place.

One SQLite file (`paths.DATABASE`) holds everything the build produces and
everything the Flask app reads:

  build_layers.py   fills  layers
  build_events.py   fills  flood_events, flood_reports, weather_stations,
                           weather_observations, rainfall_station_years,
                           nws_flood_reports, nfip_claims, nfip_policies_by_year
  both              note what they loaded in  data_sources
  run_*.py          keep   live_signals (and its two bookkeeping tables) current
                           while the app runs

A build script replaces only its own tables, in one transaction, so either can
be re-run on its own and the app never sees a half-written table. The reading
side is `src/rgv_flood/data_access.py`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import NamedTuple

from paths import DATABASE

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
             geojson_gzip BLOB NOT NULL,           -- gzipped UTF-8 FeatureCollection, sent to the browser as is
             etag TEXT NOT NULL                    -- changes whenever the GeoJSON does
           )""",
    ),
    # Every flood-type event NOAA's Storm Events Database records for the four
    # counties. source_lon/source_lat are the coordinate as NOAA published it;
    # lon/lat are what the map plots, and are null when NOAA gave no point or
    # gave one outside the county (geometry_note then says so).
    "flood_events": (
        """CREATE TABLE IF NOT EXISTS flood_events (
             id TEXT PRIMARY KEY,
             county TEXT NOT NULL,
             date TEXT NOT NULL,
             date_end TEXT,
             type TEXT NOT NULL,
             location TEXT NOT NULL,
             precision TEXT NOT NULL,              -- 'exact' or 'county'
             summary TEXT NOT NULL,
             narrative TEXT NOT NULL,              -- NOAA's own event or episode narrative
             source_url TEXT NOT NULL,
             source_lon REAL,
             source_lat REAL,
             lon REAL,
             lat REAL,
             geometry_note TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS flood_events_by_county_date ON flood_events(county, date)",
    ),
    # Hand-curated local-news and local-government reports (from data/seed/).
    "flood_reports": (
        """CREATE TABLE IF NOT EXISTS flood_reports (
             id TEXT PRIMARY KEY,
             county TEXT NOT NULL,
             headline TEXT NOT NULL,               -- the first sentence of detail
             detail TEXT NOT NULL,
             location TEXT NOT NULL,
             location_precision TEXT,
             event_date TEXT,
             event_end TEXT,
             published_at TEXT,
             publisher TEXT NOT NULL,
             channel TEXT NOT NULL,
             source_url TEXT,
             original_content TEXT,
             duplicate_group TEXT,                 -- reports about the same flood share one
             retrieved_at TEXT
           )""",
    ),
    "weather_stations": (
        """CREATE TABLE IF NOT EXISTS weather_stations (
             station_id TEXT PRIMARY KEY,          -- GHCN-Daily id
             county TEXT NOT NULL,
             name TEXT NOT NULL,
             lon REAL NOT NULL,
             lat REAL NOT NULL,
             elevation_m REAL,
             source_url TEXT NOT NULL
           )""",
    ),
    # Daily station readings, 2000-2025, as NOAA publishes them: no unit
    # conversion. PRCP is tenths of a millimetre, TMAX/TMIN tenths of a degree
    # Celsius, AWND tenths of a metre per second. Readings NOAA flagged for
    # quality are left out.
    "weather_observations": (
        """CREATE TABLE IF NOT EXISTS weather_observations (
             station_id TEXT NOT NULL REFERENCES weather_stations(station_id),
             date TEXT NOT NULL,
             element TEXT NOT NULL,                -- PRCP, TMAX, TMIN or AWND
             value REAL NOT NULL,
             measurement_flag TEXT,
             source_flag TEXT,
             observation_time_flag TEXT,
             PRIMARY KEY (station_id, date, element)
           ) WITHOUT ROWID""",
        "CREATE INDEX IF NOT EXISTS weather_observations_by_value ON weather_observations(element, value)",
    ),
    # One row per station and year: how complete its rain record is and what it
    # recorded, so yearly rainfall can be compared only where the record is whole.
    "rainfall_station_years": (
        """CREATE TABLE IF NOT EXISTS rainfall_station_years (
             station_id TEXT NOT NULL REFERENCES weather_stations(station_id),
             year INTEGER NOT NULL,
             days_reported INTEGER NOT NULL,       -- days with a rain reading NOAA didn't flag
             total_tenths_mm REAL NOT NULL,
             wettest_day_tenths_mm REAL NOT NULL,
             days_over_2_inches INTEGER NOT NULL,
             PRIMARY KEY (station_id, year)
           ) WITHOUT ROWID""",
    ),
    # Flooding the public, police, emergency managers and spotters reported to
    # NWS Brownsville (Local Storm Reports), 2005 on.
    "nws_flood_reports": (
        """CREATE TABLE IF NOT EXISTS nws_flood_reports (
             id TEXT PRIMARY KEY,
             county TEXT NOT NULL,
             kind TEXT NOT NULL,                   -- flash_flood, flood, heavy_rain or coastal_flood
             reported_at TEXT NOT NULL,            -- UTC
             city TEXT,
             remark TEXT,
             source TEXT,                          -- who reported it
             magnitude REAL,                       -- inches, for heavy rain reports
             lon REAL,
             lat REAL
           )""",
        "CREATE INDEX IF NOT EXISTS nws_flood_reports_by_county_time ON nws_flood_reports(county, reported_at)",
    ),
    # Every NFIP flood-insurance claim FEMA publishes for the four counties, 1978 on.
    "nfip_claims": (
        """CREATE TABLE IF NOT EXISTS nfip_claims (
             id TEXT PRIMARY KEY,                  -- FEMA's own claim id
             county TEXT NOT NULL,
             date_of_loss TEXT,
             year_of_loss INTEGER NOT NULL,
             flood_event TEXT,                     -- FEMA's name for the flood, where it gave one
             cause_of_damage TEXT,
             paid_building REAL NOT NULL,
             paid_contents REAL NOT NULL,
             paid_increased_cost_of_compliance REAL NOT NULL,
             building_damage REAL,
             contents_damage REAL,
             rated_flood_zone TEXT,
             occupancy_type INTEGER,
             census_tract TEXT,
             lon REAL,                             -- rounded by FEMA to protect privacy
             lat REAL
           )""",
        "CREATE INDEX IF NOT EXISTS nfip_claims_by_county_year ON nfip_claims(county, year_of_loss)",
    ),
    # NFIP policies in force per county and year (from data/seed/), the
    # denominator that turns a claim count into a rate.
    "nfip_policies_by_year": (
        """CREATE TABLE IF NOT EXISTS nfip_policies_by_year (
             county TEXT NOT NULL,
             year INTEGER NOT NULL,
             policies INTEGER NOT NULL,
             PRIMARY KEY (county, year)
           ) WITHOUT ROWID""",
    ),
    # Where each dataset in this database came from and when it was fetched.
    "data_sources": (
        """CREATE TABLE IF NOT EXISTS data_sources (
             id TEXT PRIMARY KEY,
             publisher TEXT NOT NULL,
             dataset TEXT NOT NULL,
             url TEXT,
             retrieved_at TEXT,                    -- null for seed files, which are not downloaded
             record_count INTEGER,
             notes TEXT
           )""",
    ),
    # Current official signals (NWS alerts, road conditions, county notices).
    # Written by live_signals.LiveSignalStore, which documents the lifecycle.
    "live_signals": (
        """CREATE TABLE IF NOT EXISTS live_signals (
             signal_id INTEGER PRIMARY KEY,
             source TEXT NOT NULL,
             native_id TEXT NOT NULL,
             provenance TEXT NOT NULL CHECK (provenance IN ('official', 'public-report')),
             source_url TEXT NOT NULL,
             source_publisher TEXT NOT NULL,
             source_channel TEXT NOT NULL,
             summary TEXT NOT NULL,
             source_attributes_json TEXT NOT NULL,
             county_slugs_json TEXT NOT NULL,
             inclusion_basis TEXT NOT NULL,
             source_geometry_json TEXT,
             geometry_absence_reason TEXT,
             is_mappable INTEGER NOT NULL CHECK (is_mappable IN (0, 1)),
             published_at TEXT,
             effective_at TEXT,
             source_updated_at TEXT,
             expires_at TEXT,
             first_seen_at TEXT NOT NULL,
             last_seen_at TEXT NOT NULL,
             retrieved_at TEXT NOT NULL,
             lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'inactive', 'withdrawn', 'archived')),
             terminal_at TEXT,
             terminal_reason TEXT,
             absent_success_count INTEGER NOT NULL DEFAULT 0,
             UNIQUE(source, native_id),
             CHECK ((source_geometry_json IS NOT NULL AND geometry_absence_reason IS NULL AND is_mappable = 1)
               OR (source_geometry_json IS NULL AND geometry_absence_reason IS NOT NULL AND is_mappable = 0))
           )""",
        "CREATE INDEX IF NOT EXISTS live_signals_live_lookup ON live_signals(source, lifecycle_state, last_seen_at)",
    ),
    "live_signal_runs": (
        """CREATE TABLE IF NOT EXISTS live_signal_runs (
             run_id INTEGER PRIMARY KEY,
             source TEXT NOT NULL,
             retrieved_at TEXT NOT NULL,
             completed_at TEXT,
             is_complete INTEGER NOT NULL CHECK (is_complete IN (0, 1)),
             received_count INTEGER NOT NULL,
             error_message TEXT
           )""",
    ),
    "live_signal_tombstones": (
        """CREATE TABLE IF NOT EXISTS live_signal_tombstones (
             source TEXT NOT NULL,
             native_id TEXT NOT NULL,
             terminal_at TEXT NOT NULL,
             terminal_reason TEXT NOT NULL,
             purge_after TEXT NOT NULL,
             PRIMARY KEY(source, native_id)
           )""",
    ),
}


class MapLayer(NamedTuple):
    """A built layer: its GeoJSON FeatureCollection as text, and how many features it holds."""

    geojson: str
    feature_count: int


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create whatever tables are missing, so any one writer leaves a database
    the app can query in full."""
    for statements in TABLES.values():
        for statement in statements:
            connection.execute(statement)


@contextmanager
def open_database(path: Path = DATABASE) -> Iterator[sqlite3.Connection]:
    """Open the database for one all-or-nothing write, creating it if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_schema(connection)
        yield connection


def _insert(connection: sqlite3.Connection, verb: str, table: str, rows: list[dict]) -> None:
    if rows:
        columns = list(rows[0])
        connection.executemany(
            f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})", rows
        )


def replace_table(connection: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    """Swap a table's contents for `rows` (dicts keyed by column name).

    The table is dropped and re-created rather than emptied, so a change to its
    definition above takes effect on the next build without a migration.
    """
    connection.execute(f"DROP TABLE IF EXISTS {table}")
    for statement in TABLES[table]:
        connection.execute(statement)
    _insert(connection, "INSERT", table, rows)


def record_sources(connection: sqlite3.Connection, sources: list[dict]) -> None:
    """Add or update `data_sources` rows. Unlike the other tables this one is
    shared by both build scripts, so each updates only its own rows."""
    _insert(connection, "INSERT OR REPLACE", "data_sources", sources)
