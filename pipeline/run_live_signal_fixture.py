"""Run the deterministic live-signal fixture without touching historical data.

Run: uv run python pipeline/run_live_signal_fixture.py
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from layer_io import LIVE_SIGNALS_DB, REPO_ROOT
from live_signals import LiveSignalStore

DEFAULT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "live-signals" / "official-signals.json"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=LIVE_SIGNALS_DB)
    arguments = parser.parse_args()
    store = LiveSignalStore(arguments.output)
    result = store.ingest_fixture(arguments.fixture, retrieved_at=datetime.now(UTC))
    print(f"fixture stored: {result.inserted} inserted, {result.updated} updated")


if __name__ == "__main__":
    main()
