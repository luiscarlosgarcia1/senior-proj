"""Fail-closed evaluation of source-faithful DriveTexas closure evidence.

This module deliberately decides only whether current official closure coverage
can support routing.  It never turns an absent record into a road-open claim.
Routing adapters may use ``hard_restrictions`` only after this policy permits a
route; everything else remains reviewable caution evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

DRIVE_TEXAS_SOURCES = ("drivetexas:points", "drivetexas:lines")
FRESHNESS_BUDGET = timedelta(minutes=30)
HARD_BLOCKING_CONDITION_CODES = frozenset(("F", "Z"))


class MatchBasis(StrEnum):
    """How a source geometry was related to the candidate route."""

    CONSERVATIVE_ROUTE_MATCH = "conservative_route_match"
    UNMATCHED = "unmatched"
    UNKNOWN = "unknown"


class RestrictionDisposition(StrEnum):
    HARD_RESTRICTION = "hard_restriction"
    CAUTION = "caution"


@dataclass(frozen=True)
class FeedCoverage:
    """The outcome of one source's last attempted snapshot."""

    source: str
    publisher: str
    official_conditions_url: str
    completed_at: datetime | None
    is_complete: bool
    retrieval_failure: str | None = None
    corridor_covered: bool = True


@dataclass(frozen=True)
class ClosureRecord:
    """An unmodified official record plus an explicit route-match outcome."""

    source: str
    native_id: str
    source_url: str
    publisher: str
    retrieved_at: datetime
    geometry: dict | None
    attributes: dict
    match_basis: MatchBasis

    @property
    def condition_type_code(self) -> str:
        return str(self.attributes.get("condition_type_code") or "")


@dataclass(frozen=True)
class FeedStatus:
    source: str
    publisher: str
    official_conditions_url: str
    status: str
    completed_at: datetime | None
    age: timedelta | None
    limitation: str


@dataclass(frozen=True)
class EvaluatedRestriction:
    """Reviewable result retaining source identity, geometry, and attributes."""

    native_id: str
    source: str
    source_url: str
    publisher: str
    retrieved_at: datetime
    geometry: dict | None
    attributes: dict
    condition_type_code: str
    match_basis: MatchBasis
    disposition: RestrictionDisposition
    limitation: str | None = None


@dataclass(frozen=True)
class ClosureAssessment:
    status: str
    can_publish_route: bool
    feeds: tuple[FeedStatus, ...]
    hard_restrictions: tuple[EvaluatedRestriction, ...]
    cautions: tuple[EvaluatedRestriction, ...]
    limitations: tuple[str, ...]

    @property
    def official_condition_links(self) -> tuple[str, ...]:
        return tuple(feed.official_conditions_url for feed in self.feeds)


class ClosureEvidencePolicy:
    """Evaluate DriveTexas coverage without making unsupported road claims."""

    def __init__(self, freshness_budget: timedelta = FRESHNESS_BUDGET) -> None:
        self._freshness_budget = freshness_budget

    def assess(
        self,
        coverage: tuple[FeedCoverage, ...],
        records: tuple[ClosureRecord, ...],
        now: datetime,
    ) -> ClosureAssessment:
        feeds = self._feed_statuses(coverage, now)
        coverage_is_usable = all(feed.status == "current" for feed in feeds)
        hard_restrictions: list[EvaluatedRestriction] = []
        cautions: list[EvaluatedRestriction] = []
        for record in records:
            evaluated = self._evaluate_record(record, now)
            if coverage_is_usable and evaluated.disposition == RestrictionDisposition.HARD_RESTRICTION:
                hard_restrictions.append(evaluated)
            else:
                cautions.append(evaluated if evaluated.disposition == RestrictionDisposition.CAUTION else self._as_caution(evaluated, "closure coverage is not current"))
        if coverage_is_usable:
            return ClosureAssessment("advisory", True, feeds, tuple(hard_restrictions), tuple(cautions), ())
        statuses = {feed.status for feed in feeds}
        status = "uncertain" if {"unavailable", "failed"} & statuses else "suppressed"
        return ClosureAssessment(
            status,
            False,
            feeds,
            (),
            tuple(cautions),
            ("Official closure coverage is incomplete or not current; this is not evidence that roads are open.",),
        )

    def _feed_statuses(self, coverage: tuple[FeedCoverage, ...], now: datetime) -> tuple[FeedStatus, ...]:
        by_source = {item.source: item for item in coverage}
        statuses = []
        for source in DRIVE_TEXAS_SOURCES:
            item = by_source.get(source)
            if item is None:
                statuses.append(FeedStatus(source, "TxDOT", "", "unavailable", None, None, "required official feed has no snapshot"))
                continue
            age = self._valid_age(item.completed_at, now)
            if item.retrieval_failure:
                status, limitation = "failed", item.retrieval_failure
            elif not item.corridor_covered:
                status, limitation = "incomplete", "official feed cannot validate the relevant route corridor"
            elif not item.is_complete:
                status, limitation = "incomplete", "latest official snapshot did not complete"
            elif age is None:
                if item.completed_at is None:
                    limitation = "latest official snapshot has no completion time"
                else:
                    limitation = "latest official snapshot has an invalid completion time"
                status = "unavailable"
            elif age > self._freshness_budget:
                status, limitation = "stale", "latest official snapshot exceeds the freshness budget"
            else:
                status, limitation = "current", "complete snapshot is within the freshness budget"
            statuses.append(FeedStatus(source, item.publisher, item.official_conditions_url, status, item.completed_at, age, limitation))
        return tuple(statuses)

    def _evaluate_record(self, record: ClosureRecord, now: datetime) -> EvaluatedRestriction:
        age = self._valid_age(record.retrieved_at, now)
        fresh = age is not None and age <= self._freshness_budget
        hard_restriction = (
            record.condition_type_code in HARD_BLOCKING_CONDITION_CODES
            and record.match_basis == MatchBasis.CONSERVATIVE_ROUTE_MATCH
            and fresh
        )
        limitation = None
        if age is None:
            limitation = "official record has an invalid retrieval time"
        elif not fresh:
            limitation = "official record exceeds the freshness budget"
        elif record.condition_type_code not in HARD_BLOCKING_CONDITION_CODES:
            limitation = "condition type is not a verified closure or flooding restriction"
        elif record.match_basis != MatchBasis.CONSERVATIVE_ROUTE_MATCH:
            limitation = "record lacks a conservative route match"
        return EvaluatedRestriction(
            record.native_id, record.source, record.source_url, record.publisher, record.retrieved_at,
            record.geometry, record.attributes, record.condition_type_code, record.match_basis,
            RestrictionDisposition.HARD_RESTRICTION if hard_restriction else RestrictionDisposition.CAUTION,
            limitation,
        )

    @staticmethod
    def _valid_age(timestamp: datetime | None, now: datetime) -> timedelta | None:
        """Return an age only for timestamps safe to use as current evidence."""
        if not isinstance(timestamp, datetime) or not isinstance(now, datetime):
            return None
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return None
        if now.tzinfo is None or now.utcoffset() is None:
            return None
        if timestamp > now:
            return None
        return now - timestamp

    @staticmethod
    def _as_caution(record: EvaluatedRestriction, limitation: str) -> EvaluatedRestriction:
        return EvaluatedRestriction(
            record.native_id, record.source, record.source_url, record.publisher, record.retrieved_at,
            record.geometry, record.attributes, record.condition_type_code, record.match_basis,
            RestrictionDisposition.CAUTION, limitation,
        )
