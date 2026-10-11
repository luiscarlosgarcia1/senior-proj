"""Fetch and persist Hidalgo County's official Public Notice RSS feed.

Run: uv run python pipeline/run_hidalgo_rss.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from hidalgo_rss import HIDALGO_PUBLIC_NOTICE_FEED, ingest_hidalgo_public_notices
from live_signals import LiveSignalStore, runner_parser
from net import get_bytes


def main() -> None:
    arguments = runner_parser(__doc__).parse_args()
    feed_xml = get_bytes(HIDALGO_PUBLIC_NOTICE_FEED, timeout=30)
    result = ingest_hidalgo_public_notices(LiveSignalStore(arguments.output), feed_xml, retrieved_at=datetime.now(UTC))
    print(f"Hidalgo public notices stored: {result}")


if __name__ == "__main__":
    main()
