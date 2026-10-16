#!/usr/bin/env python3
"""One command builds the central database, `data/generated/rgv-flood.sqlite3`.

Every source is pulled into memory and written straight to the database; no
data files are generated along the way. Steps, in order:

  1. build_events.py    flood events, local reports, weather stations and their
                        daily readings (NOAA Storm Events and GHCN-Daily, plus the
                        curated reports in data/seed/)
  2. build_history.py   the year-by-year record: NFIP claims and policies, NWS
                        flood reports, each rain gauge's yearly totals
  3. build_layers.py    every map layer (seed GeoJSON in data/seed/, waterways,
                        the state flood plan, city drainage, Overture bridges,
                        the Hidalgo drainage district's layers, NWS flood
                        reports, FEMA insurance claims by census tract)

Then the database is compacted, so space freed by rows a step dropped is given
back instead of left inside the file.

The publishers' own files are kept in the gitignored `tmp/` download cache, so a
rebuild only fetches what is missing; delete that folder to download everything
fresh. `data/seed/` holds the few inputs that cannot be downloaded.

Run:  uv run --group pipeline python pipeline/build_all.py
Safe to re-run: each step replaces only its own tables, in one transaction.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from paths import DATABASE, REPO_ROOT

STEPS = [
    ("flood events, reports and weather", "pipeline/build_events.py"),
    ("claims, policies and the yearly record", "pipeline/build_history.py"),
    ("map layers", "pipeline/build_layers.py"),
]


def record_build_date(database: Path, when: str) -> None:
    """Note when the build finished (shown in the app's footer and by /health)."""
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS build_info (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT OR REPLACE INTO build_info VALUES ('built_at', ?)", (when,))


def main() -> None:
    for number, (title, script) in enumerate(STEPS, start=1):
        # Flushed so each heading lands above its step's own output.
        print(f"\n== {number}/{len(STEPS)} {title} ==\n$ python {script}", flush=True)
        subprocess.run([sys.executable, script], check=True, cwd=REPO_ROOT)
    record_build_date(DATABASE, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    before = DATABASE.stat().st_size
    with closing(sqlite3.connect(DATABASE)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fold the WAL into the file first
        connection.execute("VACUUM")
    print(f"\ncompacted: {before / 2**20:,.0f} MB -> {DATABASE.stat().st_size / 2**20:,.0f} MB")
    print(f"Done: {DATABASE.relative_to(REPO_ROOT)} is up to date.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"step failed ({error.returncode}): {' '.join(error.cmd)}") from error
