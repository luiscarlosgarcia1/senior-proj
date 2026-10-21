from datetime import UTC, datetime, timedelta

from rgv_flood.wayfinder import (
    RGV_PROVIDER_QUALIFICATION_SUITE,
    AdvisoryStatus,
    Coordinate,
    Evidence,
    ProviderRouteResult,
    RouteProfile,
    WayfinderBoundary,
    WrittenResponderAuthorization,
    evaluate_provider_qualification,
)

NOW = datetime(2026, 10, 21, tzinfo=UTC)


class CapturingProvider:
    def __init__(self, result: ProviderRouteResult):
        self.result = result
        self.request = None

    def advise(self, request):
        self.request = request
        return self.result


def result(status=AdvisoryStatus.ADVISORY, **changes):
    values = {
        "status": status,
        "reasons": ("official closure overlay checked",),
        "limitations": ("advisory only; follow official emergency guidance",),
        "evidence": (),
        "retrieved_at": NOW,
        "route_segment_ids": ("open-road",),
    }
    values.update(changes)
    return ProviderRouteResult(**values)


def test_public_boundary_hard_codes_the_public_profile_and_preserves_provider_context():
    evidence = Evidence("TxDOT", "https://example.test/closure", NOW, NOW + timedelta(minutes=15))
    provider = CapturingProvider(result(evidence=(evidence,)))
    advisory = WayfinderBoundary(provider).public_advisory(
        Coordinate(26.2, -98.2), Coordinate(26.1, -98.1), ("closure-a",)
    )

    assert provider.request.profile == RouteProfile.PUBLIC
    assert provider.request.blocked_segment_ids == ("closure-a",)
    assert advisory.status == provider.result.status
    assert advisory.reasons == provider.result.reasons
    assert advisory.limitations == provider.result.limitations
    assert advisory.evidence == (evidence,)
    assert advisory.retrieved_at == NOW


def test_public_boundary_suppresses_a_route_that_contains_a_blocked_segment():
    provider = CapturingProvider(result(route_segment_ids=("open-road", "closure-a")))

    advisory = WayfinderBoundary(provider).public_advisory(
        Coordinate(26.2, -98.2), Coordinate(26.1, -98.1), ("closure-a",)
    )

    assert advisory.status == AdvisoryStatus.SUPPRESSED
    assert advisory.route_segment_ids == ()
    assert "route withheld because it includes a blocked segment" in advisory.reasons
    assert "provider route included a caller-supplied blocked segment" in advisory.limitations


def test_public_boundary_suppresses_a_route_when_provider_reports_violations():
    provider = CapturingProvider(result(provider_violations=("avoided restriction was violated",)))

    advisory = WayfinderBoundary(provider).public_advisory(
        Coordinate(26.2, -98.2), Coordinate(26.1, -98.1)
    )

    assert advisory.status == AdvisoryStatus.SUPPRESSED
    assert advisory.route_segment_ids == ()
    assert "route withheld because the provider reported safety violations" in advisory.reasons
    assert "provider-reported violations prevent publishing a route" in advisory.limitations


def test_responder_profile_needs_a_complete_current_written_authorization():
    provider = CapturingProvider(result())
    incomplete = WrittenResponderAuthorization("", "County", NOW, NOW + timedelta(days=1), "RGV")
    expired = WrittenResponderAuthorization("permit-1", "County", NOW - timedelta(days=2), NOW - timedelta(days=1), "RGV")
    complete = WrittenResponderAuthorization("permit-1", "County", NOW - timedelta(days=1), NOW + timedelta(days=1), "RGV")

    assert not WayfinderBoundary(provider).responder_profile_is_available(NOW)
    assert not WayfinderBoundary(provider, incomplete).responder_profile_is_available(NOW)
    assert not WayfinderBoundary(provider, expired).responder_profile_is_available(NOW)
    assert WayfinderBoundary(provider, complete).responder_profile_is_available(NOW)


def test_qualification_suite_covers_every_required_rgv_condition():
    ids = {case.id for case in RGV_PROVIDER_QUALIFICATION_SUITE}
    assert ids == {
        "urban-mcallen", "rural-starr", "farm-to-market", "bridge", "low-water-crossing",
        "blocked-with-alternative", "blocked-no-route", "provider-violation", "provider-outage",
    }


class ScenarioProvider:
    def advise(self, request):
        blocked = set(request.blocked_segment_ids)
        if not blocked:
            return result(AdvisoryStatus.SUPPRESSED, reasons=("provider outage",), route_segment_ids=())
        if blocked == {"closure-a", "closure-b"}:
            return result(AdvisoryStatus.NO_ROUTE, route_segment_ids=())
        return result(route_segment_ids=("open-road",))


def test_qualification_rejects_routes_that_violate_a_blocked_segment():
    class ViolatingProvider(ScenarioProvider):
        def advise(self, request):
            return result(route_segment_ids=("closure-a",))

    failures = evaluate_provider_qualification(ViolatingProvider(), (RGV_PROVIDER_QUALIFICATION_SUITE[5],))
    assert failures[0].reason == "route includes a deliberately blocked segment"


def test_qualification_rejects_missing_outage_disclosure():
    provider = CapturingProvider(result(AdvisoryStatus.SUPPRESSED, reasons=("unavailable",), route_segment_ids=()))
    failures = evaluate_provider_qualification(provider, (RGV_PROVIDER_QUALIFICATION_SUITE[-1],))
    assert failures[-1].reason == "suppression does not disclose the provider outage"
