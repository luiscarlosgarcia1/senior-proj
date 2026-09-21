"""Source-faithful storage for short-lived official incident signals.

This module deliberately owns a database separate from the historical county
collections. Source adapters turn their response into :class:`LiveSignal` and
call :meth:`LiveSignalStore.ingest`; they do not make historical events or
reports out of a current source claim.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

COUNTY_SLUGS = frozenset(("cameron", "hidalgo", "starr", "willacy"))
TERMINAL_RETENTION = timedelta(days=30)
TOMBSTONE_RETENTION = timedelta(days=90)


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
    inserted: int
    updated: int
    terminalized: int


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class LiveSignalStore:
    """SQLite boundary for live observations and their lifecycle evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
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
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def ingest_fixture(self, path: Path, *, retrieved_at: datetime) -> IngestionResult:
        """Load a controlled fixture through the same validation path as adapters."""
        fixture = json.loads(path.read_text(encoding="utf-8"))
        signals = [
            LiveSignal(**{**item, "county_slugs": tuple(item["county_slugs"])})
            for item in fixture["signals"]
        ]
        inserted = updated = terminalized = 0
        for source in sorted({signal.source for signal in signals}):
            result = self.ingest(
                source,
                [signal for signal in signals if signal.source == source],
                retrieved_at=retrieved_at,
                reconcile=False,
            )
            inserted += result.inserted
            updated += result.updated
            terminalized += result.terminalized
        return IngestionResult(inserted, updated, terminalized)

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
            self._validate(source, signal)
        seen_ids = {signal.native_id for signal in entries}
        if len(seen_ids) != len(entries):
            raise SignalValidationError(
                "a run may contain a source-native identity only once"
            )
        observed_at = _timestamp(retrieved_at)
        if not complete:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO live_signal_runs(source, retrieved_at, is_complete, received_count) VALUES (?, ?, 0, ?)",
                    (source, observed_at, len(entries)),
                )
            return IngestionResult(0, 0, 0)
        inserted = updated = terminalized = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for signal in entries:
                    exists = connection.execute(
                        "select 1 from live_signals where source=? and native_id=?",
                        (source, signal.native_id),
                    ).fetchone()
                    values = self._values(signal, observed_at)
                    if exists:
                        connection.execute(
                            """UPDATE live_signals SET provenance=?, source_url=?, source_publisher=?,
                              source_channel=?, summary=?, source_attributes_json=?, county_slugs_json=?,
                              inclusion_basis=?, source_geometry_json=?, geometry_absence_reason=?, is_mappable=?,
                              published_at=?, effective_at=?, source_updated_at=?, expires_at=?, last_seen_at=?,
                              retrieved_at=?, lifecycle_state='active', terminal_at=NULL, terminal_reason=NULL,
                              absent_success_count=0 WHERE source=? AND native_id=?""",
                            (*values, source, signal.native_id),
                        )
                        updated += 1
                    else:
                        connection.execute(
                            """INSERT INTO live_signals (
                              source, native_id, provenance, source_url, source_publisher, source_channel, summary,
                              source_attributes_json, county_slugs_json, inclusion_basis, source_geometry_json,
                              geometry_absence_reason, is_mappable, published_at, effective_at, source_updated_at,
                              expires_at, first_seen_at, last_seen_at, retrieved_at, lifecycle_state)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                            (
                                source,
                                signal.native_id,
                                *values[:-2],
                                observed_at,
                                *values[-2:],
                            ),
                        )
                        inserted += 1
                if reconcile:
                    terminalized = self._reconcile_absent(
                        connection, source, seen_ids, observed_at
                    )
                connection.execute(
                    "INSERT INTO live_signal_runs(source, retrieved_at, completed_at, is_complete, received_count) VALUES (?, ?, ?, ?, ?)",
                    (
                        source,
                        observed_at,
                        observed_at,
                        1,
                        len(entries),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return IngestionResult(inserted, updated, terminalized)

    def _validate(self, source: str, signal: LiveSignal) -> None:
        if signal.source != source:
            raise SignalValidationError(
                "all signals in a run must belong to its source"
            )
        if not all(
            (signal.source, signal.native_id, signal.source_url, signal.summary)
        ):
            raise SignalValidationError(
                "source, native identity, source URL, and summary are required"
            )
        if signal.provenance not in {"official", "public-report"}:
            raise SignalValidationError("provenance must be official or public-report")
        if not signal.county_slugs or not set(signal.county_slugs) <= COUNTY_SLUGS:
            raise SignalValidationError(
                "signals require one or more canonical county slugs"
            )
        if signal.inclusion_basis not in {
            "source_geometry_intersection",
            "source_county_claim",
            "feed_jurisdiction",
        }:
            raise SignalValidationError("inclusion basis must be source-backed")
        if signal.source_geometry is None and not signal.geometry_absence_reason:
            raise SignalValidationError(
                "signals without source geometry require an explicit absence reason"
            )
        if signal.source_geometry is not None and signal.geometry_absence_reason:
            raise SignalValidationError("source geometry cannot have an absence reason")

    def _values(self, signal: LiveSignal, observed_at: str) -> tuple[object, ...]:
        return (
            signal.provenance,
            signal.source_url,
            signal.source_publisher,
            signal.source_channel,
            signal.summary,
            _json(signal.source_attributes),
            _json(sorted(signal.county_slugs)),
            signal.inclusion_basis,
            _json(signal.source_geometry)
            if signal.source_geometry is not None
            else None,
            signal.geometry_absence_reason,
            int(signal.source_geometry is not None),
            signal.published_at,
            signal.effective_at,
            signal.updated_at,
            signal.expires_at,
            observed_at,
            observed_at,
        )

    def _reconcile_absent(
        self,
        connection: sqlite3.Connection,
        source: str,
        seen_ids: set[str],
        observed_at: str,
    ) -> int:
        terminalized = 0
        rows = connection.execute(
            "select native_id, absent_success_count from live_signals where source=? and lifecycle_state='active'",
            (source,),
        ).fetchall()
        for native_id, absence_count in rows:
            if native_id in seen_ids:
                continue
            next_count = absence_count + 1
            if next_count >= 2:
                connection.execute(
                    """update live_signals set lifecycle_state='inactive', terminal_at=?,
                      terminal_reason='absent_from_two_successful_polls', absent_success_count=?
                      where source=? and native_id=?""",
                    (observed_at, next_count, source, native_id),
                )
                terminalized += 1
            else:
                connection.execute(
                    "update live_signals set absent_success_count=? where source=? and native_id=?",
                    (next_count, source, native_id),
                )
        return terminalized

    def purge_terminal_records(self, *, now: datetime) -> int:
        """Retain terminal detail for 30 days, then keep 90-day minimal tombstones."""
        cutoff = _timestamp(now - TERMINAL_RETENTION)
        purge_after = _timestamp(now + TOMBSTONE_RETENTION)
        with self._connect() as connection:
            rows = connection.execute(
                "select source, native_id, terminal_at, terminal_reason from live_signals "
                "where terminal_at is not null and terminal_at <= ?",
                (cutoff,),
            ).fetchall()
            connection.executemany(
                """insert into live_signal_tombstones(source, native_id, terminal_at, terminal_reason, purge_after)
                  values (?, ?, ?, ?, ?) on conflict(source, native_id) do update set
                  terminal_at=excluded.terminal_at, terminal_reason=excluded.terminal_reason, purge_after=excluded.purge_after""",
                [(*row, purge_after) for row in rows],
            )
            connection.executemany(
                "delete from live_signals where source=? and native_id=?",
                [(source, native_id) for source, native_id, _, _ in rows],
            )
            connection.execute(
                "delete from live_signal_tombstones where purge_after <= ?",
                (_timestamp(now),),
            )
        return len(rows)
