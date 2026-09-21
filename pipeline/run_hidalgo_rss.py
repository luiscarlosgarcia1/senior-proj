"""Fetch and persist Hidalgo County's official Public Notice RSS feed.

Run: uv run python pipeline/run_hidalgo_rss.py
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from hidalgo_rss import HIDALGO_PUBLIC_NOTICE_FEED, ingest_hidalgo_public_notices
from live_signals import LiveSignalStore

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "generated" / "live-signals.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    request = Request(
        HIDALGO_PUBLIC_NOTICE_FEED,
        headers={"User-Agent": "RGV-Flood-Impact-Visualizer/1.0"},
    )
    with urlopen(request, timeout=30) as response:  # nosec B310
        feed_xml = response.read()
    result = ingest_hidalgo_public_notices(
        LiveSignalStore(arguments.output), feed_xml, retrieved_at=datetime.now(UTC)
    )
    print(
        f"Hidalgo public notices stored: {result.inserted} inserted, "
        f"{result.updated} updated, {result.terminalized} terminalized"
    )


if __name__ == "__main__":
    main()
