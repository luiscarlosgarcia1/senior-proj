"""Run the deterministic live-signal fixture without touching historical data.

Run: uv run python pipeline/run_live_signal_fixture.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from live_signals import LiveSignalStore, runner_parser
from paths import REPO_ROOT

DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "live-signals" / "official-signals.json"


def main() -> None:
    parser = runner_parser(__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    arguments = parser.parse_args()
    result = LiveSignalStore(arguments.output).ingest_fixture(arguments.fixture, retrieved_at=datetime.now(UTC))
    print(f"fixture stored: {result}")


if __name__ == "__main__":
    main()
