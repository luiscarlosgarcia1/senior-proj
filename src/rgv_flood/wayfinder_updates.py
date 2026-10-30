"""Validated soft-risk policy and visible Wayfinder route-update proposals.

This module intentionally cannot publish, replace, dispatch, or navigate a
route.  It evaluates non-closure signals only against locally validated,
versioned associations, and turns any reevaluation into an explicit proposal
for the caller to show a traveler.  Official closure validation remains owned
by :mod:`rgv_flood.wayfinder_advisories`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Protocol

from rgv_flood.wayfinder import AdvisoryStatus, Coordinate
from rgv_flood.wayfinder_advisories import (
    AdvisoryProvenance,
    VerifiedAdvisory,
    VerifiedPublicAdvisoryService,
)
from rgv_flood.wayfinder_closures import ClosureAssessment


class RefreshTrigger(StrEnum):
    RESTRICTION_CHANGED = "restriction_changed"
    RESTRICTION_EXPIRED = "restriction_expired"
    RISK_THRESHOLD_CROSSED = "risk_threshold_crossed"
    MATERIAL_DEPARTURE = "material_departure"
    TRAFFIC_ETA_EXPIRED = "traffic_eta_expired"


class AuthoritativeCondition(IntEnum):
    """Ordered conditions; a larger value is the more restrictive outcome."""

    UNKNOWN = 0
    LIMITED = 1
    CLOSED = 2


@dataclass(frozen=True)
class AuthoritativeRestriction:
    restriction_id: str
    condition: AuthoritativeCondition
    effective_at: datetime
    expires_at: datetime | None

    def is_current(self, checked_at: datetime) -> bool:
        return self.effective_at <= checked_at and (
            self.expires_at is None or checked_at < self.expires_at
        )


@dataclass(frozen=True)
class SoftRiskPolicy:
    """A locally validated rule associating one signal with one road feature."""

    policy_id: str
    version: str
    source: str
    threshold: float
    penalty: float
    route_corridor_id: str
    affected_feature_id: str
    validated_at: datetime
    validation_reference: str

    def applies_to(self, signal: SoftRiskSignal) -> bool:
        return (
            bool(self.policy_id and self.version and self.validation_reference)
            and self.source == signal.source
            and self.route_corridor_id == signal.route_corridor_id
            and self.affected_feature_id == signal.affected_feature_id
            and signal.value >= self.threshold
        )


@dataclass(frozen=True)
class SoftRiskSignal:
    evidence_id: str
    source: str
    value: float
    observed_at: datetime
    route_corridor_id: str | None
    affected_feature_id: str | None


@dataclass(frozen=True)
class AppliedSoftPenalty:
    policy_id: str
    policy_version: str
    evidence_id: str
    penalty: float
    reason: str


@dataclass(frozen=True)
class SoftRiskEvaluation:
    penalties: tuple[AppliedSoftPenalty, ...]
    cautions: tuple[str, ...]
    request_closure_refresh: bool

    @property
    def total_penalty(self) -> float:
        return sum(item.penalty for item in self.penalties)


class SoftRiskPolicyEvaluator:
    """Applies only documented, validated signal-to-feature policy records."""

    def evaluate(
        self, policies: tuple[SoftRiskPolicy, ...], signals: tuple[SoftRiskSignal, ...]
    ) -> SoftRiskEvaluation:
        penalties: list[AppliedSoftPenalty] = []
        cautions: list[str] = []
        for signal in signals:
            matches = tuple(policy for policy in policies if policy.applies_to(signal))
            if not matches:
                cautions.append(
                    f"{signal.evidence_id} remains a caution: no locally validated policy "
                    "connects this signal to this route corridor and road/crossing."
                )
                continue
            for policy in matches:
                penalties.append(
                    AppliedSoftPenalty(
                        policy.policy_id,
                        policy.version,
                        signal.evidence_id,
                        policy.penalty,
                        f"{signal.source} crossed locally validated threshold {policy.threshold} "
                        f"for {policy.affected_feature_id}",
                    )
                )
        return SoftRiskEvaluation(tuple(penalties), tuple(cautions), bool(cautions))


def most_restrictive_current_outcome(
    restrictions: tuple[AuthoritativeRestriction, ...], checked_at: datetime
) -> AuthoritativeCondition:
    """Resolve current conflicts without treating expired closures as reopened."""
    current = [item.condition for item in restrictions if item.is_current(checked_at)]
    return max(current, default=AuthoritativeCondition.UNKNOWN)


@dataclass(frozen=True)
class ProposedRouteUpdate:
    """A user-visible candidate; callers must never replace an active route with it."""

    active_advisory_id: str
    advisory: VerifiedAdvisory
    trigger: RefreshTrigger
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    soft_penalties: tuple[AppliedSoftPenalty, ...]

    @property
    def public_message(self) -> str:
        return "A route update is proposed for your review; it has not replaced your active advisory."


@dataclass(frozen=True)
class ReevaluationAuditEvent:
    """Operational output deliberately excludes origin, destination, and user IDs."""

    trigger: RefreshTrigger
    policy_versions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    match_reasons: tuple[str, ...]
    provider_status: str
    validation_outcome: str
    validation_record: AdvisoryProvenance
    user_visible_result: str


class CurrentClosureAssessmentSource(Protocol):
    """Supplies a fresh official-closure assessment for one reevaluation."""

    def assess_current(self, checked_at: datetime) -> ClosureAssessment: ...


class ReevaluationClock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class ReevaluationResult:
    """A result produced by the provider-bound, current-overlay path only."""

    advisory: VerifiedAdvisory
    verified: bool
    reason: str


class VerifiedAdvisoryReevaluation:
    """Own complete route reevaluation for one active advisory request.

    This is deliberately a concrete integration seam, rather than an arbitrary
    callback.  It couples the active route coordinates, the current official
    closure assessment, and the already provider/configuration-bound advisory
    service.  A caller cannot hand :class:`RouteUpdateProposer` a fabricated
    ``VerifiedAdvisory`` and have it appear as a route update.
    """

    def __init__(
        self,
        advisory_service: VerifiedPublicAdvisoryService,
        closure_assessments: CurrentClosureAssessmentSource,
        origin: Coordinate,
        destination: Coordinate,
        clock: ReevaluationClock,
    ) -> None:
        self._advisory_service = advisory_service
        self._closure_assessments = closure_assessments
        self._origin = origin
        self._destination = destination
        self._clock = clock

    def reevaluate(self) -> ReevaluationResult:
        checked_at = self._clock.now()
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("reevaluation clock must return an aware timestamp")
        assessment = self._closure_assessments.assess_current(checked_at)
        advisory = self._advisory_service.advise(
            self._origin, self._destination, assessment, checked_at
        )
        provenance = advisory.provenance
        if provenance.checked_at != checked_at:
            return ReevaluationResult(advisory, False, "reevaluation validation record is stale")
        if provenance.provider_status != advisory.advisory.status:
            return ReevaluationResult(advisory, False, "reevaluation provider status is inconsistent")
        if (
            advisory.advisory.status is not AdvisoryStatus.ADVISORY
            or provenance.validation_outcome != "complete official overlay validation passed"
            or provenance.qualification_record_id is None
            or provenance.qualification_suite_version is None
        ):
            return ReevaluationResult(
                advisory,
                False,
                "current provider and official-overlay validation did not produce an eligible advisory",
            )
        return ReevaluationResult(advisory, True, "complete current reevaluation passed")


class RouteUpdateProposer:
    """Requests a complete reevaluation and exposes only a proposed update."""

    def __init__(self, reevaluation: VerifiedAdvisoryReevaluation) -> None:
        if type(reevaluation) is not VerifiedAdvisoryReevaluation:
            raise TypeError("route updates require a provider-bound verified reevaluation")
        self._reevaluation = reevaluation

    def propose(
        self,
        *,
        active_advisory_id: str,
        trigger: RefreshTrigger,
        risk_evaluation: SoftRiskEvaluation,
    ) -> tuple[ProposedRouteUpdate | None, ReevaluationAuditEvent]:
        """Propose only a current, provider-bound, overlay-validated advisory."""
        reevaluation = self._reevaluation.reevaluate()
        reevaluated = reevaluation.advisory
        penalties = risk_evaluation.penalties
        reasons = tuple(item.reason for item in penalties) + risk_evaluation.cautions
        if not reevaluation.verified:
            event = ReevaluationAuditEvent(
                trigger,
                tuple(sorted({item.policy_version for item in penalties})),
                tuple(item.evidence_id for item in penalties),
                (*reasons, reevaluation.reason),
                str(reevaluated.provenance.provider_status),
                reevaluated.provenance.validation_outcome,
                reevaluated.provenance,
                "No route update is proposed because current reevaluation could not be verified.",
            )
            return None, event
        limitations = (
            *reevaluated.advisory.limitations,
            "Soft-risk context does not establish that a road is safe, open, or passable.",
        )
        proposal = ProposedRouteUpdate(
            active_advisory_id,
            reevaluated,
            trigger,
            reasons,
            limitations,
            penalties,
        )
        event = ReevaluationAuditEvent(
            trigger,
            tuple(sorted({item.policy_version for item in penalties})),
            tuple(item.evidence_id for item in penalties),
            reasons,
            str(reevaluated.provenance.provider_status),
            reevaluated.provenance.validation_outcome,
            reevaluated.provenance,
            proposal.public_message,
        )
        return proposal, event
