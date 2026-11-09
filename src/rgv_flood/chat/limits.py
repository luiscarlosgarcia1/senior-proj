"""How many chat messages a visitor may send a day.

Counts live in their own small SQLite file, never in the project's database
(which the app only reads). Keys (a visitor id, an IP address, an email) are
stored only as salted hashes, and a day's counts are dropped after three days.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ANON_DAILY = 5  # a visitor who has not signed in, per browser
ANON_IP_DAILY = 25  # and per network address, so clearing cookies is not a way round it
SIGNED_IN_DAILY = 200  # a safety ceiling for @utrgv.edu accounts, not a quota
KEEP_DAYS = 3

VALLEY = ZoneInfo("America/Chicago")


def valley_day(now: datetime | None = None) -> str:
    """The calendar day in the Rio Grande Valley (`YYYY-MM-DD`); counts reset at its midnight."""
    return (now or datetime.now(UTC)).astimezone(VALLEY).date().isoformat()


class UsageStore:
    def __init__(self, path: Path, pepper: str):
        self.path = Path(path)
        self.pepper = pepper
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, key_hash TEXT NOT NULL, count INTEGER NOT NULL, "
                "PRIMARY KEY (day, key_hash)) WITHOUT ROWID"
            )

    def _connect(self) -> closing:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        return closing(connection)

    def _hash(self, key: str) -> str:
        return hashlib.sha256((self.pepper + key).encode()).hexdigest()

    def try_consume(self, limits: dict[str, int], *, now: datetime | None = None) -> bool:
        """Count one message against every key in `limits` ({key: daily limit}), or count nothing
        and return False if any of them is already at its limit. All or nothing, in one transaction."""
        day = valley_day(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for key, limit in limits.items():
                    row = connection.execute(
                        "SELECT count FROM usage WHERE day = ? AND key_hash = ?", (day, self._hash(key))
                    ).fetchone()
                    if row and row[0] >= limit:
                        connection.execute("ROLLBACK")
                        return False
                for key in limits:
                    connection.execute(
                        "INSERT INTO usage (day, key_hash, count) VALUES (?, ?, 1) "
                        "ON CONFLICT (day, key_hash) DO UPDATE SET count = count + 1",
                        (day, self._hash(key)),
                    )
                cutoff = (datetime.fromisoformat(day) - timedelta(days=KEEP_DAYS)).date().isoformat()
                connection.execute("DELETE FROM usage WHERE day < ?", (cutoff,))
                connection.execute("COMMIT")
                return True
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def refund(self, keys: list[str], *, now: datetime | None = None) -> None:
        """Give one message back to each key (for a message that got no answer)."""
        day = valley_day(now)
        with self._connect() as connection:
            for key in keys:
                connection.execute(
                    "UPDATE usage SET count = MAX(count - 1, 0) WHERE day = ? AND key_hash = ?", (day, self._hash(key))
                )

    def used(self, key: str, *, now: datetime | None = None) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT count FROM usage WHERE day = ? AND key_hash = ?", (valley_day(now), self._hash(key))
            ).fetchone()
        return row[0] if row else 0
