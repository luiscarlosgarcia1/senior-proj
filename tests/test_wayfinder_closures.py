from datetime import UTC, datetime, timedelta

from rgv_flood.wayfinder_closures import (
    ClosureEvidencePolicy,
    ClosureRecord,
    FeedCoverage,
    MatchBasis,
    RestrictionDisposition,
)

NOW = datetime(2026, 10, 21, 18, tzinfo=UTC)


def coverage(source: str, *, completed_at: datetime = NOW, complete: bool = True) -> FeedCoverage:
    return FeedCoverage(source, "DriveTexas", "https://example.test/feed", completed_at, complete)


def record(
    native_id: str,
    *,
    condition: str = "Z",
    matched: MatchBasis = MatchBasis.CONSERVATIVE_ROUTE_MATCH,
    retrieved_at: datetime = NOW,
) -> ClosureRecord:
    return ClosureRecord(
        source="drivetexas:lines",
        native_id=native_id,
        source_url=f"https://example.test/records/{native_id}",
        publisher="Texas Department of Transportation (TxDOT)",
        retrieved_at=retrieved_at,
        geometry={"type": "LineString", "coordinates": [[-98.2, 26.2], [-98.1, 26.3]]},
        attributes={"condition_type_code": condition, "OBJECTID": native_id},
        match_basis=matched,
    )


def test_incomplete_or_stale_required_feed_suppresses_the_advisory_with_source_details():
    assessment = ClosureEvidencePolicy().assess(
        (coverage("drivetexas:points", complete=False), coverage("drivetexas:lines", completed_at=NOW - timedelta(minutes=31))),
        (),
        NOW,
    )

    assert assessment.can_publish_route is False
    assert assessment.status == "suppressed"
    assert {item.source for item in assessment.feeds} == {"drivetexas:points", "drivetexas:lines"}
    assert all(item.age is not None for item in assessment.feeds)
    assert "not evidence that roads are open" in assessment.limitations[0]
    assert assessment.official_condition_links == (
        "https://example.test/feed", "https://example.test/feed"
    )


def test_missing_required_feed_is_uncertain_and_never_treated_as_clear_coverage():
    assessment = ClosureEvidencePolicy().assess((coverage("drivetexas:points"),), (), NOW)

    assert assessment.can_publish_route is False
    assert assessment.status == "uncertain"
    unavailable = next(item for item in assessment.feeds if item.source == "drivetexas:lines")
    assert unavailable.status == "unavailable"


def test_failed_or_corridor_incomplete_coverage_is_uncertain_not_an_open_road_inference():
    assessment = ClosureEvidencePolicy().assess(
        (
            FeedCoverage("drivetexas:points", "DriveTexas", "https://example.test/points", NOW, False, "request failed"),
            FeedCoverage("drivetexas:lines", "DriveTexas", "https://example.test/lines", NOW, True, None, False),
        ),
        (),
        NOW,
    )

    assert assessment.status == "uncertain"
    assert {item.status for item in assessment.feeds} == {"failed", "incomplete"}
    assert assessment.can_publish_route is False


def test_only_fresh_authoritative_conservatively_matched_flood_or_closure_is_a_hard_restriction():
    policy = ClosureEvidencePolicy()
    assessment = policy.assess(
        (coverage("drivetexas:points"), coverage("drivetexas:lines")),
        (
            record("closure"),
            record("flood", condition="F"),
            record("unknown", condition="Q"),
            record("unmatched", matched=MatchBasis.UNMATCHED),
            record("stale", retrieved_at=NOW - timedelta(minutes=31)),
        ),
        NOW,
    )

    assert assessment.can_publish_route is True
    assert [item.native_id for item in assessment.hard_restrictions] == ["closure", "flood"]
    assert {item.native_id for item in assessment.cautions} == {"unknown", "unmatched", "stale"}
    assert all(item.disposition == RestrictionDisposition.CAUTION for item in assessment.cautions)
    assert assessment.cautions[0].geometry is not None
    assert assessment.cautions[0].attributes


def test_unknown_condition_and_unknown_match_remain_visible_cautions_without_an_inferred_status():
    assessment = ClosureEvidencePolicy().assess(
        (coverage("drivetexas:points"), coverage("drivetexas:lines")),
        (
            record("unknown-condition", condition=""),
            record("unknown-match", matched=MatchBasis.UNKNOWN),
        ),
        NOW,
    )

    assert assessment.hard_restrictions == ()
    assert [item.match_basis for item in assessment.cautions] == [MatchBasis.CONSERVATIVE_ROUTE_MATCH, MatchBasis.UNKNOWN]
    assert all(item.disposition == RestrictionDisposition.CAUTION for item in assessment.cautions)
