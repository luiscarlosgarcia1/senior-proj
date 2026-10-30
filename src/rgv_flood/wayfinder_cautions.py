"""Conservative, source-attributed non-closure evidence for Wayfinder.

This policy deliberately has no route-exclusion output. Dynamic weather and
hydrologic observations can make public context more useful and ask the
authoritative closure collector for a refresh, but they never establish that a
road is closed, open, safe, or passable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class NonClosureSource(StrEnum):
    NWS_CAP = "nws:cap"
    OFFICIAL_RADAR_QPE = "official:radar-qpe"
    NWPS = "nws:nwps"
    NWM = "noaa:nwm"
    OPEN_METEO_HRRR = "open-meteo:hrrr"


class RetrievalOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"


class CautionFreshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


SOURCE_FRESHNESS_BUDGETS: dict[NonClosureSource, timedelta] = {
    NonClosureSource.NWS_CAP: timedelta(minutes=15),
    NonClosureSource.OFFICIAL_RADAR_QPE: timedelta(minutes=15),
    NonClosureSource.NWPS: timedelta(hours=1),
    NonClosureSource.NWM: timedelta(hours=1),
    # This secondary/development-only feed is never authoritative road evidence.
    NonClosureSource.OPEN_METEO_HRRR: timedelta(hours=2),
}

SOURCE_LIMITATIONS: dict[NonClosureSource, str] = {
    NonClosureSource.NWS_CAP: "Flood-hazard context is not a road-condition determination.",
    NonClosureSource.OFFICIAL_RADAR_QPE: "Radar and precipitation estimates are not road-condition determinations.",
    NonClosureSource.NWPS: "Hydrologic observations and forecasts are not road-condition determinations.",
    NonClosureSource.NWM: "Hydrologic model analysis and forecasts are not road-condition determinations.",
    NonClosureSource.OPEN_METEO_HRRR: "Secondary development-only forecast context is not road-condition evidence.",
}


@dataclass(frozen=True)
class NonClosureEvidence:
    """An unmodified dynamic source snapshot with its acquisition context."""

    source: NonClosureSource
    publisher: str
    source_url: str
    publisher_timestamp: datetime | None
    coverage: str
    geometry: dict | None
    geometry_note: str | None
    retrieval_outcome: RetrievalOutcome
    is_complete: bool
    retrieved_at: datetime
    attributes: dict


@dataclass(frozen=True)
class NonClosureCaution:
    """Public, reviewable context that cannot alter road-status policy."""

    source: NonClosureSource
    publisher: str
    source_url: str
    publisher_timestamp: datetime | None
    age: timedelta | None
    freshness: CautionFreshness
    coverage: str
    geometry: dict | None
    geometry_note: str | None
    retrieval_outcome: RetrievalOutcome
    is_complete: bool
    attributes: dict
    limitation: str


@dataclass(frozen=True)
class NonClosureAssessment:
    cautions: tuple[NonClosureCaution, ...]
    request_authoritative_closure_refresh: bool
    refresh_reasons: tuple[str, ...]

    @property
    def hard_restrictions(self) -> tuple[()]:
        """Non-closure evidence never creates a hard route restriction."""
        return ()

    @property
    def public_policy_statement(self) -> str:
        return (
            "Weather, radar, hydrology, forecasts, traffic, crowdsourced reports, "
            "and susceptibility are context only; only verified official closure "
            "evidence can establish a route restriction."
        )


class NonClosureEvidencePolicy:
    """Turn permitted dynamic sources into conservative, visible cautions."""

    def assess(
        self, evidence: tuple[NonClosureEvidence, ...], now: datetime
    ) -> NonClosureAssessment:
        cautions = tuple(self._as_caution(item, now) for item in evidence)
        reasons = tuple(
            f"{caution.source}: {caution.freshness} non-closure evidence requires official closure refresh"
            for caution in cautions
            if caution.freshness is not CautionFreshness.CURRENT
            or caution.retrieval_outcome is not RetrievalOutcome.SUCCESS
            or not caution.is_complete
        )
        return NonClosureAssessment(cautions, bool(reasons), reasons)

    @staticmethod
    def _as_caution(item: NonClosureEvidence, now: datetime) -> NonClosureCaution:
        age = _valid_age(item.publisher_timestamp, now)
        budget = SOURCE_FRESHNESS_BUDGETS[item.source]
        if item.retrieval_outcome is not RetrievalOutcome.SUCCESS:
            freshness = CautionFreshness.UNAVAILABLE
            condition = f"retrieval outcome is {item.retrieval_outcome}"
        elif not item.is_complete:
            freshness = CautionFreshness.UNAVAILABLE
            condition = "source snapshot is incomplete"
        elif age is None:
            freshness = CautionFreshness.UNAVAILABLE
            condition = "publisher timestamp is absent or invalid"
        elif age > budget:
            freshness = CautionFreshness.STALE
            condition = f"source exceeds its {budget} freshness budget"
        else:
            freshness = CautionFreshness.CURRENT
            condition = "source is current"
        return NonClosureCaution(
            item.source,
            item.publisher,
            item.source_url,
            item.publisher_timestamp,
            age,
            freshness,
            item.coverage,
            item.geometry,
            item.geometry_note,
            item.retrieval_outcome,
            item.is_complete,
            item.attributes,
            f"{condition}. {SOURCE_LIMITATIONS[item.source]}",
        )


def _valid_age(timestamp: datetime | None, now: datetime) -> timedelta | None:
    if not isinstance(timestamp, datetime) or not isinstance(now, datetime):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    if now.tzinfo is None or now.utcoffset() is None or timestamp > now:
        return None
    return now - timestamp
