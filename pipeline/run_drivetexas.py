"""Poll the two approved DriveTexas layers no more frequently than 15 minutes.

Run: uv run --group pipeline python pipeline/run_drivetexas.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from drivetexas import (
    DRIVE_TEXAS_COUNTY_CODES,
    DRIVE_TEXAS_LAYERS,
    fetch_drivetexas_page,
    ingest_drivetexas_snapshot,
)
from layer_io import DATA_DIR, LIVE_SIGNALS_DB
from live_signals import LiveSignalStore


def _county_boundaries() -> dict[str, dict]:
    return {
        slug: json.loads(
            (DATA_DIR / f"{slug}-county" / "flood-hazard-layers" / "boundary.geojson").read_text(encoding="utf-8")
        )["features"][0]["geometry"]
        for slug in DRIVE_TEXAS_COUNTY_CODES
    }


def _was_polled_within_15_minutes(store: LiveSignalStore, now: datetime) -> bool:
    """Keep this manual runner within TxDOT's documented 15-minute cadence."""
    sources = tuple(f"drivetexas:{layer.key}" for layer in DRIVE_TEXAS_LAYERS)
    if not store.path.exists():
        return False
    with closing(sqlite3.connect(store.path)) as connection:
        rows = connection.execute(
            "select source, max(completed_at) from live_signal_runs "
            "where source in (?, ?) and is_complete=1 group by source",
            sources,
        ).fetchall()
    completed = {
        source: datetime.fromisoformat(value)
        for source, value in rows
        if value
    }
    return len(completed) == len(sources) and all(
        now - completed[source] < timedelta(minutes=15) for source in sources
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=LIVE_SIGNALS_DB)
    arguments = parser.parse_args()
    store = LiveSignalStore(arguments.output)
    if _was_polled_within_15_minutes(store, datetime.now(UTC)):
        print("DriveTexas poll skipped: a complete snapshot ran within 15 minutes")
        return
    result = ingest_drivetexas_snapshot(
        store,
        _county_boundaries(),
        fetch_page=fetch_drivetexas_page,
        retrieved_at=datetime.now(UTC),
    )
    print(f"DriveTexas signals: {result.inserted} inserted, {result.updated} updated, {result.terminalized} terminalized")


if __name__ == "__main__":
    main()
