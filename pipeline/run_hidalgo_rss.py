"""Fetch and persist Hidalgo County's official Public Notice RSS feed.

Run: uv run python pipeline/run_hidalgo_rss.py
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from hidalgo_rss import HIDALGO_PUBLIC_NOTICE_FEED, ingest_hidalgo_public_notices
from layer_io import LIVE_SIGNALS_DB
from live_signals import LiveSignalStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=LIVE_SIGNALS_DB)
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
