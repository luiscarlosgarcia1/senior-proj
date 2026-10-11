"""Poll the two approved DriveTexas layers no more frequently than 15 minutes.

Run: uv run --group pipeline python pipeline/run_drivetexas.py
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

from drivetexas import (
    DRIVE_TEXAS_COUNTY_CODES,
    DRIVE_TEXAS_LAYERS,
    fetch_drivetexas_page,
    ingest_drivetexas_snapshot,
)
from live_signals import LiveSignalStore, runner_parser
from paths import county_boundary

# TxDOT's documented cadence; this runner will not poll more often.
MINIMUM_INTERVAL = timedelta(minutes=15)


def _polled_recently(store: LiveSignalStore, now: datetime) -> bool:
    """True when every layer already has a complete snapshot inside the interval."""
    sources = [layer.source for layer in DRIVE_TEXAS_LAYERS]
    with closing(sqlite3.connect(store.path)) as connection:
        rows = connection.execute(
            "select source, max(completed_at) from live_signal_runs "
            f"where source in ({', '.join('?' * len(sources))}) and is_complete=1 group by source",
            sources,
        ).fetchall()
    last_completed = {source: datetime.fromisoformat(value) for source, value in rows if value}
    return all(source in last_completed and now - last_completed[source] < MINIMUM_INTERVAL for source in sources)


def main() -> None:
    arguments = runner_parser(__doc__).parse_args()
    store = LiveSignalStore(arguments.output)
    now = datetime.now(UTC)
    if _polled_recently(store, now):
        print("DriveTexas poll skipped: a complete snapshot ran within 15 minutes")
        return
    result = ingest_drivetexas_snapshot(
        store,
        {slug: county_boundary(slug) for slug in DRIVE_TEXAS_COUNTY_CODES},
        fetch_page=fetch_drivetexas_page,
        retrieved_at=now,
    )
    print(f"DriveTexas signals: {result}")


if __name__ == "__main__":
    main()
