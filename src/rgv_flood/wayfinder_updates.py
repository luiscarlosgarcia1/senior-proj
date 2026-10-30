"""Validated soft-risk policy and visible Wayfinder route-update proposals.

This module intentionally cannot publish, replace, dispatch, or navigate a
route.  It evaluates non-closure signals only against locally validated,
versioned associations, and turns any reevaluation into an explicit proposal
for the caller to show a traveler.  Official closure validation remains owned
by :mod:`rgv_flood.wayfinder_advisories`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum

from rgv_flood.wayfinder_advisories import VerifiedAdvisory


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
    user_visible_result: str


class RouteUpdateProposer:
    """Requests a complete reevaluation and exposes only a proposed update."""

    def propose(
        self,
        *,
        active_advisory_id: str,
        trigger: RefreshTrigger,
        risk_evaluation: SoftRiskEvaluation,
        reevaluate: Callable[[], VerifiedAdvisory],
    ) -> tuple[ProposedRouteUpdate, ReevaluationAuditEvent]:
        """Run a caller-supplied current-overlay reevaluation exactly once.

        The callable is the integration seam for the existing verified advisory
        service; it must obtain fresh official coverage and geometry validation.
        Its returned provenance is preserved in both the proposal and health
        event so operators can review the actual validation result.
        """
        reevaluated = reevaluate()
        penalties = risk_evaluation.penalties
        reasons = tuple(item.reason for item in penalties) + risk_evaluation.cautions
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
            proposal.public_message,
        )
        return proposal, event
