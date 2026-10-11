"""Source-faithful storage for short-lived official incident signals.

This module deliberately owns a database separate from the historical county
collections. Source adapters turn their response into :class:`LiveSignal` and
call :meth:`LiveSignalStore.ingest`; they do not make historical events or
reports out of a current source claim.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonio import canonical_json
from paths import LIVE_SIGNALS_DB

from rgv_flood.counties import COUNTIES

COUNTY_SLUGS = frozenset(COUNTIES)
PROVENANCES = frozenset(("official", "public-report"))
INCLUSION_BASES = frozenset(("source_geometry_intersection", "source_county_claim", "feed_jurisdiction"))
# A signal missing from this many complete polls in a row is treated as over.
# One absence can be an upstream hiccup, so it never closes a signal on its own.
ABSENCES_BEFORE_INACTIVE = 2
TERMINAL_RETENTION = timedelta(days=30)
TOMBSTONE_RETENTION = timedelta(days=90)

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_signals (
  signal_id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  provenance TEXT NOT NULL CHECK (provenance IN ('official', 'public-report')),
  source_url TEXT NOT NULL,
  source_publisher TEXT NOT NULL,
  source_channel TEXT NOT NULL,
  summary TEXT NOT NULL,
  source_attributes_json TEXT NOT NULL,
  county_slugs_json TEXT NOT NULL,
  inclusion_basis TEXT NOT NULL,
  source_geometry_json TEXT,
  geometry_absence_reason TEXT,
  is_mappable INTEGER NOT NULL CHECK (is_mappable IN (0, 1)),
  published_at TEXT,
  effective_at TEXT,
  source_updated_at TEXT,
  expires_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'inactive', 'withdrawn', 'archived')),
  terminal_at TEXT,
  terminal_reason TEXT,
  absent_success_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(source, native_id),
  CHECK ((source_geometry_json IS NOT NULL AND geometry_absence_reason IS NULL AND is_mappable = 1)
    OR (source_geometry_json IS NULL AND geometry_absence_reason IS NOT NULL AND is_mappable = 0))
);
CREATE TABLE IF NOT EXISTS live_signal_runs (
  run_id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  completed_at TEXT,
  is_complete INTEGER NOT NULL CHECK (is_complete IN (0, 1)),
  received_count INTEGER NOT NULL,
  error_message TEXT
);
CREATE TABLE IF NOT EXISTS live_signal_tombstones (
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  terminal_at TEXT NOT NULL,
  terminal_reason TEXT NOT NULL,
  purge_after TEXT NOT NULL,
  PRIMARY KEY(source, native_id)
);
CREATE INDEX IF NOT EXISTS live_signals_live_lookup
  ON live_signals(source, lifecycle_state, last_seen_at);
"""

# What a poll writes for each signal. A signal seen again keeps its row and its
# first_seen_at, takes every other value from the new poll, and becomes active.
_POLLED_COLUMNS = (
    "source", "native_id", "provenance", "source_url", "source_publisher", "source_channel", "summary",
    "source_attributes_json", "county_slugs_json", "inclusion_basis", "source_geometry_json",
    "geometry_absence_reason", "is_mappable", "published_at", "effective_at", "source_updated_at",
    "expires_at", "first_seen_at", "last_seen_at", "retrieved_at",
)
_KEPT_WHEN_SEEN_AGAIN = ("source", "native_id", "first_seen_at")
_UPSERT = f"""
INSERT INTO live_signals ({", ".join(_POLLED_COLUMNS)}, lifecycle_state)
VALUES ({", ".join(":" + column for column in _POLLED_COLUMNS)}, 'active')
ON CONFLICT(source, native_id) DO UPDATE SET
  {", ".join(f"{c}=excluded.{c}" for c in _POLLED_COLUMNS if c not in _KEPT_WHEN_SEEN_AGAIN)},
  lifecycle_state='active', terminal_at=NULL, terminal_reason=NULL, absent_success_count=0
"""


class SignalValidationError(ValueError):
    """A source adapter attempted to persist a non-source-faithful signal."""


@dataclass(frozen=True)
class LiveSignal:
    source: str
    native_id: str
    provenance: str
    source_url: str
    source_publisher: str
    source_channel: str
    summary: str
    source_attributes: dict
    county_slugs: tuple[str, ...]
    inclusion_basis: str
    source_geometry: dict | None
    geometry_absence_reason: str | None = None
    published_at: str | None = None
    effective_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class IngestionResult:
    inserted: int = 0
    updated: int = 0
    terminalized: int = 0

    def __add__(self, other: IngestionResult) -> IngestionResult:
        return IngestionResult(
            self.inserted + other.inserted,
            self.updated + other.updated,
            self.terminalized + other.terminalized,
        )

    def __str__(self) -> str:
        return f"{self.inserted} inserted, {self.updated} updated, {self.terminalized} terminalized"


def utc_timestamp(value: datetime) -> str:
    """ISO 8601 in UTC with a trailing Z, the one timestamp format stored here."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def runner_parser(description: str) -> argparse.ArgumentParser:
    """Command-line parser shared by the run_*.py scripts: every one takes --output."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--output", type=Path, default=LIVE_SIGNALS_DB, help="live-signals SQLite database")
    return parser


def _validate(source: str, signal: LiveSignal) -> None:
    if signal.source != source:
        raise SignalValidationError("all signals in a run must belong to its source")
    if not all((signal.source, signal.native_id, signal.source_url, signal.summary)):
        raise SignalValidationError("source, native identity, source URL, and summary are required")
    if signal.provenance not in PROVENANCES:
        raise SignalValidationError("provenance must be official or public-report")
    if not signal.county_slugs or not set(signal.county_slugs) <= COUNTY_SLUGS:
        raise SignalValidationError("signals require one or more canonical county slugs")
    if signal.inclusion_basis not in INCLUSION_BASES:
        raise SignalValidationError("inclusion basis must be source-backed")
    if signal.source_geometry is None and not signal.geometry_absence_reason:
        raise SignalValidationError("signals without source geometry require an explicit absence reason")
    if signal.source_geometry is not None and signal.geometry_absence_reason:
        raise SignalValidationError("source geometry cannot have an absence reason")


def _row(signal: LiveSignal, observed_at: str) -> dict[str, object]:
    """The signal as live_signals column values (the keys of _POLLED_COLUMNS)."""
    has_geometry = signal.source_geometry is not None
    return {
        "source": signal.source,
        "native_id": signal.native_id,
        "provenance": signal.provenance,
        "source_url": signal.source_url,
        "source_publisher": signal.source_publisher,
        "source_channel": signal.source_channel,
        "summary": signal.summary,
        "source_attributes_json": canonical_json(signal.source_attributes),
        "county_slugs_json": canonical_json(sorted(signal.county_slugs)),
        "inclusion_basis": signal.inclusion_basis,
        "source_geometry_json": canonical_json(signal.source_geometry) if has_geometry else None,
        "geometry_absence_reason": signal.geometry_absence_reason,
        "is_mappable": int(has_geometry),
        "published_at": signal.published_at,
        "effective_at": signal.effective_at,
        "source_updated_at": signal.updated_at,
        "expires_at": signal.expires_at,
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "retrieved_at": observed_at,
    }


class LiveSignalStore:
    """SQLite boundary for live observations and their lifecycle evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits (or rolls back) and then actually closes.

        sqlite3's own context manager only commits; the file would stay open
        until garbage collection.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            yield connection

    def ingest_fixture(self, path: Path, *, retrieved_at: datetime) -> IngestionResult:
        """Load a controlled fixture through the same validation path as adapters."""
        fixture = json.loads(path.read_text(encoding="utf-8"))
        signals = [LiveSignal(**{**item, "county_slugs": tuple(item["county_slugs"])}) for item in fixture["signals"]]
        total = IngestionResult()
        for source in sorted({signal.source for signal in signals}):
            total += self.ingest(
                source,
                [signal for signal in signals if signal.source == source],
                retrieved_at=retrieved_at,
                reconcile=False,
            )
        return total

    def ingest(
        self,
        source: str,
        signals: Iterable[LiveSignal],
        *,
        retrieved_at: datetime,
        complete: bool = True,
        reconcile: bool = True,
    ) -> IngestionResult:
        """Atomically record one source poll.

        A non-complete run is recorded but cannot affect previous observations.
        Complete snapshots terminalize a missing source record only after it has
        been absent from two successful runs, protecting data during transient
        upstream failures.
        """
        entries = list(signals)
        for signal in entries:
            _validate(source, signal)
        seen_ids = {signal.native_id for signal in entries}
        if len(seen_ids) != len(entries):
            raise SignalValidationError("a run may contain a source-native identity only once")
        observed_at = utc_timestamp(retrieved_at)

        with self._connect() as connection:
            if not complete:
                connection.execute(
                    "INSERT INTO live_signal_runs(source, retrieved_at, is_complete, received_count) VALUES (?, ?, 0, ?)",
                    (source, observed_at, len(entries)),
                )
                return IngestionResult()

            connection.execute("BEGIN IMMEDIATE")
            known_ids = {
                native_id
                for (native_id,) in connection.execute("SELECT native_id FROM live_signals WHERE source=?", (source,))
            }
            connection.executemany(_UPSERT, [_row(signal, observed_at) for signal in entries])
            terminalized = self._reconcile_absent(connection, source, seen_ids, observed_at) if reconcile else 0
            connection.execute(
                "INSERT INTO live_signal_runs(source, retrieved_at, completed_at, is_complete, received_count) "
                "VALUES (?, ?, ?, 1, ?)",
                (source, observed_at, observed_at, len(entries)),
            )
        inserted = len(seen_ids - known_ids)
        return IngestionResult(inserted, len(entries) - inserted, terminalized)

    def _reconcile_absent(
        self, connection: sqlite3.Connection, source: str, seen_ids: set[str], observed_at: str
    ) -> int:
        """Count this poll against every active signal it did not contain, and
        deactivate the ones that have now been missing often enough."""
        active = connection.execute(
            "SELECT native_id FROM live_signals WHERE source=? AND lifecycle_state='active'", (source,)
        )
        absent = [(source, native_id) for (native_id,) in active if native_id not in seen_ids]
        connection.executemany(
            "UPDATE live_signals SET absent_success_count = absent_success_count + 1 WHERE source=? AND native_id=?",
            absent,
        )
        # Signals seen in this poll were just reset to zero, so only absent ones can match.
        deactivated = connection.execute(
            """UPDATE live_signals SET lifecycle_state='inactive', terminal_at=?,
                 terminal_reason='absent_from_two_successful_polls'
               WHERE source=? AND lifecycle_state='active' AND absent_success_count >= ?""",
            (observed_at, source, ABSENCES_BEFORE_INACTIVE),
        )
        return deactivated.rowcount

    def purge_terminal_records(self, *, now: datetime) -> int:
        """Retain terminal detail for 30 days, then keep 90-day minimal tombstones."""
        cutoff = utc_timestamp(now - TERMINAL_RETENTION)
        purge_after = utc_timestamp(now + TOMBSTONE_RETENTION)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source, native_id, terminal_at, terminal_reason FROM live_signals "
                "WHERE terminal_at IS NOT NULL AND terminal_at <= ?",
                (cutoff,),
            ).fetchall()
            connection.executemany(
                """INSERT INTO live_signal_tombstones(source, native_id, terminal_at, terminal_reason, purge_after)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(source, native_id) DO UPDATE SET
                   terminal_at=excluded.terminal_at, terminal_reason=excluded.terminal_reason,
                   purge_after=excluded.purge_after""",
                [(*row, purge_after) for row in rows],
            )
            connection.executemany(
                "DELETE FROM live_signals WHERE source=? AND native_id=?",
                [(source, native_id) for source, native_id, _, _ in rows],
            )
            connection.execute("DELETE FROM live_signal_tombstones WHERE purge_after <= ?", (utc_timestamp(now),))
        return len(rows)
