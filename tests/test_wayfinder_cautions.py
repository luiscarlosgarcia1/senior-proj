from datetime import UTC, datetime, timedelta

import pytest

from rgv_flood.wayfinder_cautions import (
    SOURCE_FRESHNESS_BUDGETS,
    CautionFreshness,
    NonClosureEvidence,
    NonClosureEvidencePolicy,
    NonClosureSource,
    RetrievalOutcome,
)

NOW = datetime(2026, 10, 30, 18, tzinfo=UTC)


def _evidence(source: NonClosureSource, **changes) -> NonClosureEvidence:
    values = {
        "source": source,
        "publisher": "Official source",
        "source_url": f"https://example.test/{source}",
        "publisher_timestamp": NOW,
        "coverage": "Rio Grande Valley",
        "geometry": {"type": "Point", "coordinates": [-98.2, 26.2]},
        "geometry_note": None,
        "retrieval_outcome": RetrievalOutcome.SUCCESS,
        "is_complete": True,
        "retrieved_at": NOW,
        "attributes": {"source_field": "preserved"},
    }
    values.update(changes)
    return NonClosureEvidence(**values)


@pytest.mark.parametrize("source", tuple(NonClosureSource))
def test_permitted_sources_preserve_source_metadata_as_visible_cautions(source: NonClosureSource):
    assessment = NonClosureEvidencePolicy().assess((_evidence(source),), NOW)

    caution = assessment.cautions[0]
    assert caution.source is source
    assert caution.publisher_timestamp == NOW
    assert caution.coverage == "Rio Grande Valley"
    assert caution.geometry == {"type": "Point", "coordinates": [-98.2, 26.2]}
    assert caution.retrieval_outcome is RetrievalOutcome.SUCCESS
    assert caution.attributes == {"source_field": "preserved"}
    assert caution.freshness is CautionFreshness.CURRENT
    assert assessment.hard_restrictions == ()


def test_stale_nonclosure_evidence_remains_visible_and_requests_closure_refresh():
    source = NonClosureSource.NWPS
    stale = _evidence(source, publisher_timestamp=NOW - SOURCE_FRESHNESS_BUDGETS[source] - timedelta(seconds=1))

    assessment = NonClosureEvidencePolicy().assess((stale,), NOW)

    assert assessment.cautions[0].freshness is CautionFreshness.STALE
    assert assessment.cautions[0].age is not None
    assert assessment.request_authoritative_closure_refresh
    assert assessment.hard_restrictions == ()


def test_failed_or_incomplete_evidence_is_a_caution_not_a_road_status():
    failed = _evidence(NonClosureSource.NWS_CAP, retrieval_outcome=RetrievalOutcome.FAILED, geometry=None, geometry_note="not supplied")
    incomplete = _evidence(NonClosureSource.OPEN_METEO_HRRR, is_complete=False)

    assessment = NonClosureEvidencePolicy().assess((failed, incomplete), NOW)

    assert [item.freshness for item in assessment.cautions] == [CautionFreshness.UNAVAILABLE, CautionFreshness.UNAVAILABLE]
    assert assessment.request_authoritative_closure_refresh
    assert "road-condition" in assessment.cautions[0].limitation
    assert "Secondary development-only" in assessment.cautions[1].limitation


def test_public_policy_keeps_context_distinct_from_authoritative_restrictions():
    assessment = NonClosureEvidencePolicy().assess((), NOW)

    assert "context only" in assessment.public_policy_statement
    assert "only verified official closure evidence" in assessment.public_policy_statement
