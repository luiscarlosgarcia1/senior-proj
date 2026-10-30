"""Provider-neutral safety boundary for future Wayfinder route advisories.

This module deliberately does not choose, configure, or call a routing vendor.
An adapter may implement :class:`RouteAdvisoryProvider` later, but the public
boundary always uses the public policy and reports uncertainty instead of
inventing a safe route.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class AdvisoryStatus(StrEnum):
    ADVISORY = "advisory"
    SUPPRESSED = "suppressed"
    NO_ROUTE = "no_route"


class RouteProfile(StrEnum):
    PUBLIC = "public"
    RESPONDER = "responder"


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Evidence:
    """A source fact that influenced an advisory, including its freshness."""

    source: str
    source_url: str
    observed_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class ProviderRouteRequest:
    """The provider-neutral request supplied only by the server boundary."""

    origin: Coordinate
    destination: Coordinate
    profile: RouteProfile
    blocked_segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderRouteResult:
    """An adapter's complete result, retained without vendor-specific coercion."""

    status: AdvisoryStatus
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    retrieved_at: datetime
    route_segment_ids: tuple[str, ...] = ()
    provider_violations: tuple[str, ...] = ()
    route_geometry: dict | None = None


@dataclass(frozen=True)
class RouteAdvisory:
    """The public response shape: status plus its evidence and limitations."""

    status: AdvisoryStatus
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    retrieved_at: datetime
    route_segment_ids: tuple[str, ...]
    route_geometry: dict | None = None


class RouteAdvisoryProvider(Protocol):
    """Future provider adapters implement this small, vendor-neutral seam."""

    def advise(self, request: ProviderRouteRequest) -> ProviderRouteResult: ...


@dataclass(frozen=True)
class WrittenResponderAuthorization:
    """Server-held record required before a responder profile can exist."""

    authorization_id: str
    issued_by: str
    effective_at: datetime
    expires_at: datetime
    permitted_area: str

    def is_complete_and_current(self, now: datetime) -> bool:
        return (
            all(
                (
                    self.authorization_id.strip(),
                    self.issued_by.strip(),
                    self.permitted_area.strip(),
                )
            )
            and self.effective_at <= now < self.expires_at
        )


class WayfinderBoundary:
    """Server boundary which exposes only the public advisory operation.

    No provider identifier, provider setting, or route-profile field is accepted
    from public clients. A responder capability remains unavailable unless a
    server-side authorization record is complete and current; this ticket does
    not expose a responder-routing operation.
    """

    def __init__(self, provider: RouteAdvisoryProvider, responder_authorization: WrittenResponderAuthorization | None = None):
        self._provider = provider
        self._responder_authorization = responder_authorization

    def public_advisory(
        self,
        origin: Coordinate,
        destination: Coordinate,
        blocked_segment_ids: tuple[str, ...] = (),
    ) -> RouteAdvisory:
        result = self._provider.advise(
            ProviderRouteRequest(
                origin=origin,
                destination=destination,
                profile=RouteProfile.PUBLIC,
                blocked_segment_ids=blocked_segment_ids,
            )
        )
        blocked_segments_in_route = set(result.route_segment_ids) & set(blocked_segment_ids)
        if blocked_segments_in_route or result.provider_violations:
            reasons = list(result.reasons)
            limitations = list(result.limitations)
            if blocked_segments_in_route:
                reasons.append("route withheld because it includes a blocked segment")
                limitations.append("provider route included a caller-supplied blocked segment")
            if result.provider_violations:
                reasons.append("route withheld because the provider reported safety violations")
                limitations.append("provider-reported violations prevent publishing a route")
            return RouteAdvisory(
                status=AdvisoryStatus.SUPPRESSED,
                reasons=tuple(reasons),
                limitations=tuple(limitations),
                evidence=result.evidence,
                retrieved_at=result.retrieved_at,
                route_segment_ids=(),
                route_geometry=None,
            )
        return RouteAdvisory(
            status=result.status,
            reasons=result.reasons,
            limitations=result.limitations,
            evidence=result.evidence,
            retrieved_at=result.retrieved_at,
            route_segment_ids=result.route_segment_ids,
            route_geometry=result.route_geometry,
        )

    def responder_profile_is_available(self, now: datetime) -> bool:
        return self._responder_authorization is not None and self._responder_authorization.is_complete_and_current(now)


class QualificationExpectation(StrEnum):
    ADVISORY = "advisory"
    NO_ROUTE = "no_route"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class ProviderQualificationCase:
    """A deterministic fixture a prospective provider must satisfy."""

    id: str
    description: str
    request: ProviderRouteRequest
    expected_status: QualificationExpectation
    expected_alternative: bool = False
    requires_outage_reason: bool = False


@dataclass(frozen=True)
class QualificationFailure:
    case_id: str
    reason: str


def evaluate_provider_qualification(
    provider: RouteAdvisoryProvider, cases: tuple[ProviderQualificationCase, ...] | None = None
) -> tuple[QualificationFailure, ...]:
    """Return every deterministic qualification failure; an empty tuple passes."""
    failures: list[QualificationFailure] = []
    for case in cases or RGV_PROVIDER_QUALIFICATION_SUITE:
        result = provider.advise(case.request)
        if result.status != case.expected_status:
            failures.append(QualificationFailure(case.id, f"expected {case.expected_status}, got {result.status}"))
        if set(result.route_segment_ids) & set(case.request.blocked_segment_ids):
            failures.append(QualificationFailure(case.id, "route includes a deliberately blocked segment"))
        if result.provider_violations:
            failures.append(QualificationFailure(case.id, "provider reported: " + "; ".join(result.provider_violations)))
        if case.expected_alternative and not result.route_segment_ids:
            failures.append(QualificationFailure(case.id, "expected a viable alternative route"))
        if case.requires_outage_reason and not any("outage" in reason.lower() for reason in result.reasons):
            failures.append(QualificationFailure(case.id, "suppression does not disclose the provider outage"))
    return tuple(failures)


def _request(origin: tuple[float, float], destination: tuple[float, float], *blocked: str) -> ProviderRouteRequest:
    return ProviderRouteRequest(Coordinate(*origin), Coordinate(*destination), RouteProfile.PUBLIC, blocked)


# Stable coordinates and symbolic segment IDs make the suite repeatable without
# calling a live map or routing service. Each road category is represented in a
# named fixture so provider adapters can map it to their own network IDs.
RGV_PROVIDER_QUALIFICATION_SUITE = (
    ProviderQualificationCase("urban-mcallen", "Urban McAllen trip", _request((26.204, -98.230), (26.190, -98.230)), "advisory"),
    ProviderQualificationCase("rural-starr", "Rural Starr County trip", _request((26.385, -98.820), (26.350, -98.720)), "advisory"),
    ProviderQualificationCase("farm-to-market", "Farm-to-market road trip", _request((26.270, -98.330), (26.260, -98.280)), "advisory"),
    ProviderQualificationCase("bridge", "Bridge crossing", _request((26.170, -97.695), (26.160, -97.690)), "advisory"),
    ProviderQualificationCase("low-water-crossing", "Low-water crossing", _request((26.315, -98.155), (26.305, -98.145)), "advisory"),
    ProviderQualificationCase("blocked-with-alternative", "Blocked segment with an alternative", _request((26.220, -98.250), (26.200, -98.240), "closure-a"), "advisory", True),
    ProviderQualificationCase("blocked-no-route", "All viable segments blocked", _request((26.220, -98.250), (26.200, -98.240), "closure-a", "closure-b"), "no_route"),
    ProviderQualificationCase("provider-violation", "Provider must disclose a violated restriction", _request((26.220, -98.250), (26.200, -98.240), "closure-a"), "advisory"),
    ProviderQualificationCase("provider-outage", "Provider outage is suppressed, not converted to a route", _request((26.220, -98.250), (26.200, -98.240)), "suppressed", requires_outage_reason=True),
)
