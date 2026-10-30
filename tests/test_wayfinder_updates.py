from datetime import UTC, datetime, timedelta

from rgv_flood.wayfinder import AdvisoryStatus, RouteAdvisory
from rgv_flood.wayfinder_advisories import AdvisoryProvenance, VerifiedAdvisory
from rgv_flood.wayfinder_updates import (
    AuthoritativeCondition,
    AuthoritativeRestriction,
    RefreshTrigger,
    RouteUpdateProposer,
    SoftRiskPolicy,
    SoftRiskPolicyEvaluator,
    SoftRiskSignal,
    most_restrictive_current_outcome,
)

NOW = datetime(2026, 10, 30, 18, tzinfo=UTC)


def _policy(**changes) -> SoftRiskPolicy:
    values = {
        "policy_id": "crossing-risk",
        "version": "risk-policy/v3",
        "source": "nws:nwps",
        "threshold": 12.0,
        "penalty": 8.0,
        "route_corridor_id": "rgv-83",
        "affected_feature_id": "low-water-crossing-9",
        "validated_at": NOW,
        "validation_reference": "field-study-2026-10",
    }
    values.update(changes)
    return SoftRiskPolicy(**values)


def _signal(**changes) -> SoftRiskSignal:
    values = {
        "evidence_id": "nwps-001",
        "source": "nws:nwps",
        "value": 12.5,
        "observed_at": NOW,
        "route_corridor_id": "rgv-83",
        "affected_feature_id": "low-water-crossing-9",
    }
    values.update(changes)
    return SoftRiskSignal(**values)


def _verified_advisory() -> VerifiedAdvisory:
    advisory = RouteAdvisory(
        AdvisoryStatus.ADVISORY, ("freshly validated",), ("official closures checked",), (), NOW, (),
        {"type": "LineString", "coordinates": [[-98.2, 26.2], [-98.1, 26.3]]},
    )
    return VerifiedAdvisory(
        advisory,
        AdvisoryProvenance("closure-policy/v1", NOW, AdvisoryStatus.ADVISORY, "complete official overlay validation passed", (), (), "qualification-1", "suite/v1"),
    )


def test_only_a_locally_validated_threshold_and_association_can_add_a_penalty():
    evaluation = SoftRiskPolicyEvaluator().evaluate((_policy(),), (_signal(),))

    assert evaluation.total_penalty == 8.0
    assert evaluation.penalties[0].policy_version == "risk-policy/v3"
    assert evaluation.cautions == ()


def test_missing_or_mismatched_association_stays_a_caution_and_requests_closure_refresh():
    evaluation = SoftRiskPolicyEvaluator().evaluate((_policy(),), (_signal(affected_feature_id="other-crossing"),))

    assert evaluation.penalties == ()
    assert evaluation.request_closure_refresh
    assert "remains a caution" in evaluation.cautions[0]


def test_most_restrictive_current_authoritative_condition_wins_and_expired_is_unknown():
    restrictions = (
        AuthoritativeRestriction("limited", AuthoritativeCondition.LIMITED, NOW - timedelta(minutes=1), None),
        AuthoritativeRestriction("closed", AuthoritativeCondition.CLOSED, NOW - timedelta(minutes=1), None),
        AuthoritativeRestriction("expired", AuthoritativeCondition.CLOSED, NOW - timedelta(hours=2), NOW - timedelta(minutes=1)),
    )

    assert most_restrictive_current_outcome(restrictions, NOW) is AuthoritativeCondition.CLOSED
    assert most_restrictive_current_outcome((restrictions[2],), NOW) is AuthoritativeCondition.UNKNOWN


def test_reevaluation_is_a_visible_proposal_with_audit_data_and_never_replaces_active_advisory():
    evaluation = SoftRiskPolicyEvaluator().evaluate((_policy(),), (_signal(),))
    calls = []

    def reevaluate() -> VerifiedAdvisory:
        calls.append("current-overlay-validation")
        return _verified_advisory()

    proposal, event = RouteUpdateProposer().propose(
        active_advisory_id="active-advisory-9",
        trigger=RefreshTrigger.RISK_THRESHOLD_CROSSED,
        risk_evaluation=evaluation,
        reevaluate=reevaluate,
    )

    assert calls == ["current-overlay-validation"]
    assert proposal.active_advisory_id == "active-advisory-9"
    assert "proposed for your review" in proposal.public_message
    assert "not replaced" in proposal.public_message
    assert event.trigger is RefreshTrigger.RISK_THRESHOLD_CROSSED
    assert event.policy_versions == ("risk-policy/v3",)
    assert event.evidence_ids == ("nwps-001",)
    assert event.validation_outcome == "complete official overlay validation passed"
    assert not hasattr(event, "origin")
    assert not hasattr(event, "destination")


def test_all_reevaluation_triggers_are_explicit():
    assert {item.value for item in RefreshTrigger} == {
        "restriction_changed",
        "restriction_expired",
        "risk_threshold_crossed",
        "material_departure",
        "traffic_eta_expired",
    }
