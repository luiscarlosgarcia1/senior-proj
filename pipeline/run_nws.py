"""Poll NWS active Texas alerts and store the current RGV source claims.

Run: uv run --group pipeline python pipeline/run_nws.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from live_signals import LiveSignalStore, runner_parser
from nws import run_nws_active_alert_ingestion


def main() -> None:
    arguments = runner_parser(__doc__).parse_args()
    result = run_nws_active_alert_ingestion(LiveSignalStore(arguments.output), retrieved_at=datetime.now(UTC))
    print(f"NWS alerts: {result}")


if __name__ == "__main__":
    main()
