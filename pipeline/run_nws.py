"""Poll NWS active Texas alerts and store the current RGV source claims.

Run: uv run --group pipeline python pipeline/run_nws.py
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from layer_io import LIVE_SIGNALS_DB
from live_signals import LiveSignalStore
from nws import run_nws_active_alert_ingestion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=LIVE_SIGNALS_DB)
    arguments = parser.parse_args()
    result = run_nws_active_alert_ingestion(
        LiveSignalStore(arguments.output), retrieved_at=datetime.now(UTC)
    )
    print(
        "NWS alerts: "
        f"{result.inserted} inserted, {result.updated} updated, "
        f"{result.terminalized} terminalized"
    )


if __name__ == "__main__":
    main()
