import json
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from rgv_flood.wayfinder import (
    RGV_PROVIDER_QUALIFICATION_SUITE,
    AdvisoryStatus,
    Coordinate,
    ProviderRouteResult,
)
from rgv_flood.wayfinder_advisories import (
    POLICY_VERSION,
    PUBLIC_LIMITATION,
    OfficialClosureGeometryValidator,
    OpenRouteServiceProvider,
    ProviderConfiguration,
    ProviderQualificationRecord,
    VerifiedPublicAdvisoryService,
)
from rgv_flood.wayfinder_closures import (
    ClosureEvidencePolicy,
    ClosureRecord,
    FeedCoverage,
    MatchBasis,
)

NOW = datetime(2026, 10, 30, 18, tzinfo=UTC)
ORIGIN = Coordinate(26.2, -98.2)
DESTINATION = Coordinate(26.3, -98.1)
ROUTE = {"type": "LineString", "coordinates": [[-98.2, 26.2], [-98.1, 26.3]]}


def _coverage() -> tuple[FeedCoverage, ...]:
    return (
        FeedCoverage("drivetexas:points", "TxDOT", "https://example.test/points", NOW, True),
        FeedCoverage("drivetexas:lines", "TxDOT", "https://example.test/lines", NOW, True),
    )


def _assessment(*records: ClosureRecord):
    return ClosureEvidencePolicy().assess(_coverage(), records, NOW)


def _restriction(
    identifier: str = "closure-1", geometry: dict | None = None, *, missing_geometry: bool = False
) -> ClosureRecord:
    return ClosureRecord(
        source="drivetexas:lines",
        native_id=identifier,
        source_url=f"https://example.test/{identifier}",
        publisher="TxDOT",
        retrieved_at=NOW,
        geometry=None if missing_geometry else geometry or {
            "type": "LineString", "coordinates": [[-98.2, 26.3], [-98.1, 26.2]]
        },
        attributes={"condition_type_code": "Z"},
        match_basis=MatchBasis.CONSERVATIVE_ROUTE_MATCH,
    )


class StaticProvider:
    def __init__(self, result: ProviderRouteResult, configuration: str = "fixture-v1"):
        self.result = result
        self.configuration = configuration

    def advise(self, request):
        return self.result

    def qualification_configuration(self):
        return ProviderConfiguration("fixture-provider", self.configuration)


class QualificationPassingProvider(StaticProvider):
    """A deterministic provider fixture that satisfies every RGV case."""

    def advise(self, request):
        for case in RGV_PROVIDER_QUALIFICATION_SUITE:
            if request == case.request:
                reasons = ("routing provider outage",) if case.requires_outage_reason else ("qualified fixture",)
                return _result(
                    status=AdvisoryStatus(case.expected_status),
                    reasons=reasons,
                    route_segment_ids=("fixture-alternative",) if case.expected_alternative else (),
                )
        return super().advise(request)


def _result(**changes) -> ProviderRouteResult:
    values = {
        "status": AdvisoryStatus.ADVISORY,
        "reasons": ("provider candidate",),
        "limitations": (),
        "evidence": (),
        "retrieved_at": NOW,
        "route_geometry": ROUTE,
    }
    values.update(changes)
    return ProviderRouteResult(**values)


def _qualified_service(
    result: ProviderRouteResult | None = None,
    *,
    configuration: str = "fixture-v1",
    qualified_at: datetime = NOW,
    validity: timedelta = timedelta(days=30),
) -> VerifiedPublicAdvisoryService:
    provider = QualificationPassingProvider(result or _result(), configuration)
    record = ProviderQualificationRecord.evaluate(
        provider,
        record_id="qualification-fixture-001",
        policy_version=POLICY_VERSION,
        qualified_at=qualified_at,
        validity=validity,
    )
    assert record.failures == ()
    return VerifiedPublicAdvisoryService(provider, qualification_record=record)


def test_ors_adapter_keeps_key_server_side_and_extracts_complete_geojson_geometry():
    calls = []

    def responder(request):
        calls.append(request)
        return httpx2.Response(200, json={"features": [{"geometry": ROUTE}]})

    provider = OpenRouteServiceProvider(
        "server-secret", client=httpx2.Client(transport=httpx2.MockTransport(responder))
    )
    result = provider.advise(
        type("Request", (), {"origin": ORIGIN, "destination": DESTINATION})()
    )

    assert result.status == AdvisoryStatus.ADVISORY
    assert result.route_geometry == ROUTE
    assert calls[0].headers["authorization"] == "server-secret"
    assert calls[0].url.path.endswith("/driving-car/geojson")
    assert json.loads(calls[0].content)["coordinates"] == [[-98.2, 26.2], [-98.1, 26.3]]


def test_ors_quota_failure_is_suppressed_without_route_geometry():
    provider = OpenRouteServiceProvider(
        "server-secret",
        client=httpx2.Client(transport=httpx2.MockTransport(lambda request: httpx2.Response(429))),
    )
    result = provider.advise(type("Request", (), {"origin": ORIGIN, "destination": DESTINATION})())

    assert result.status == AdvisoryStatus.SUPPRESSED
    assert result.route_geometry is None
    assert "quota" in result.reasons[0]


def test_ors_no_candidate_response_is_a_no_route_result():
    provider = OpenRouteServiceProvider(
        "server-secret",
        client=httpx2.Client(transport=httpx2.MockTransport(lambda request: httpx2.Response(404))),
    )

    result = provider.advise(type("Request", (), {"origin": ORIGIN, "destination": DESTINATION})())

    assert result.status == AdvisoryStatus.NO_ROUTE
    assert result.reasons == ("No advisory route available from current official closure data.",)


def test_service_suppresses_when_official_coverage_is_not_publishable():
    assessment = ClosureEvidencePolicy().assess((_coverage()[0],), (), NOW)
    service = _qualified_service()

    result = service.advise(ORIGIN, DESTINATION, assessment, NOW)

    assert result.advisory.status == AdvisoryStatus.SUPPRESSED
    assert result.advisory.route_geometry is None
    assert result.provenance.validation_outcome == "official closure coverage is not current"


def test_service_suppresses_a_route_that_intersects_a_verified_official_restriction():
    service = _qualified_service()

    result = service.advise(ORIGIN, DESTINATION, _assessment(_restriction()), NOW)

    assert result.advisory.status == AdvisoryStatus.SUPPRESSED
    assert result.advisory.route_geometry is None
    assert "intersects verified official restriction closure-1" in result.advisory.reasons[0]
    assert result.provenance.validation_outcome == "official overlay validation failed"


def test_service_publishes_only_a_validated_route_with_source_links_and_provenance():
    service = _qualified_service()

    result = service.advise(ORIGIN, DESTINATION, _assessment(), NOW)

    assert result.advisory.status == AdvisoryStatus.ADVISORY
    assert result.advisory.route_geometry == ROUTE
    assert PUBLIC_LIMITATION in result.advisory.limitations
    assert "Official conditions: https://example.test/points" in result.advisory.limitations
    assert result.provenance.validation_outcome == "complete official overlay validation passed"
    assert result.provenance.restriction_ids == ()
    assert result.provenance.qualification_record_id == "qualification-fixture-001"
    assert result.provenance.qualification_suite_version == "rgv-provider-qualification/v1"


def test_service_uses_the_required_message_when_provider_has_no_eligible_candidate():
    service = _qualified_service(_result(status=AdvisoryStatus.NO_ROUTE))

    result = service.advise(ORIGIN, DESTINATION, _assessment(), NOW)

    assert result.advisory.status == AdvisoryStatus.NO_ROUTE
    assert result.advisory.reasons[0] == "No advisory route available from current official closure data."
    assert result.advisory.route_geometry is None


def test_geometry_validator_fails_closed_when_a_restriction_cannot_be_checked():
    restriction = _restriction(missing_geometry=True)
    assessment = _assessment(restriction)
    service = _qualified_service()

    result = service.advise(ORIGIN, DESTINATION, assessment, NOW)

    assert result.advisory.status == AdvisoryStatus.SUPPRESSED
    assert result.advisory.route_geometry is None
    assert "has no geometry" in result.advisory.reasons[0]


def test_geometry_validator_returns_no_violation_for_a_disjoint_restriction():
    restriction = _restriction(geometry={"type": "LineString", "coordinates": [[-99.0, 27.0], [-99.1, 27.1]]})

    assert OfficialClosureGeometryValidator().validate(ROUTE, (_assessment(restriction).hard_restrictions[0],)) == ()


def test_service_suppresses_until_the_required_provider_qualification_has_passed():
    result = VerifiedPublicAdvisoryService(StaticProvider(_result())).advise(ORIGIN, DESTINATION, _assessment(), NOW)

    assert result.advisory.status == AdvisoryStatus.SUPPRESSED
    assert result.advisory.route_geometry is None
    assert result.provenance.validation_outcome == "provider qualification record is not valid for the active provider configuration"


def test_service_cannot_be_enabled_with_an_arbitrary_qualification_boolean():
    with pytest.raises(TypeError):
        VerifiedPublicAdvisoryService(StaticProvider(_result()), qualification_passed=True)


def test_service_suppresses_when_qualification_record_targets_another_provider_configuration():
    qualified_provider = QualificationPassingProvider(_result(), "approved-configuration")
    record = ProviderQualificationRecord.evaluate(
        qualified_provider,
        record_id="qualification-approved-configuration",
        policy_version=POLICY_VERSION,
        qualified_at=NOW,
    )
    other_provider = QualificationPassingProvider(_result(), "different-configuration")

    result = VerifiedPublicAdvisoryService(other_provider, qualification_record=record).advise(
        ORIGIN, DESTINATION, _assessment(), NOW
    )

    assert result.advisory.status == AdvisoryStatus.SUPPRESSED
    assert result.advisory.route_geometry is None
    assert result.provenance.qualification_record_id == "qualification-approved-configuration"


def test_service_suppresses_when_the_qualification_record_has_expired():
    service = _qualified_service(qualified_at=NOW - timedelta(days=2), validity=timedelta(days=1))

    result = service.advise(ORIGIN, DESTINATION, _assessment(), NOW)

    assert result.advisory.status == AdvisoryStatus.SUPPRESSED
    assert result.advisory.route_geometry is None
