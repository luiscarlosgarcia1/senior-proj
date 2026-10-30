"""Approved ORS routing with a final official-closure validation boundary.

This module deliberately separates route generation from publication.  ORS is
only an untrusted geometry source: a fresh DriveTexas assessment and complete
geometry validation must succeed after ORS returns before an advisory can be
shown.  Nothing here describes a road as safe, open, or passable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx2
from shapely.geometry import shape

from rgv_flood.wayfinder import (
    AdvisoryStatus,
    Coordinate,
    ProviderRouteRequest,
    ProviderRouteResult,
    RouteAdvisory,
    RouteAdvisoryProvider,
    WayfinderBoundary,
)
from rgv_flood.wayfinder_closures import ClosureAssessment, EvaluatedRestriction

ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
PUBLIC_LIMITATION = (
    "This advisory avoids currently reported fresh official closures; it does not "
    "confirm that roads are safe, open, or passable."
)
NO_ROUTE_REASON = "No advisory route available from current official closure data."
POLICY_VERSION = "wayfinder-public-closure-avoidance/v1"


class Clock(Protocol):
    def now(self) -> datetime: ...


class RouteGeometryValidator(Protocol):
    def validate(
        self, route_geometry: dict | None, restrictions: tuple[EvaluatedRestriction, ...]
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class AdvisoryProvenance:
    """Immutable facts needed to review a published or withheld decision."""

    policy_version: str
    checked_at: datetime
    provider_status: AdvisoryStatus
    validation_outcome: str
    restriction_ids: tuple[str, ...]
    source_urls: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedAdvisory:
    advisory: RouteAdvisory
    provenance: AdvisoryProvenance


class OpenRouteServiceProvider(RouteAdvisoryProvider):
    """Minimal server-only adapter for the approved ORS Standard API.

    A key is intentionally required at construction.  Callers keep it in secret
    storage; neither requests nor errors include it or the route coordinates.
    """

    def __init__(self, api_key: str, client: httpx2.Client | None = None, url: str = ORS_DIRECTIONS_URL) -> None:
        if not api_key.strip():
            raise ValueError("an ORS API key is required for server-side routing")
        self._api_key = api_key
        self._client = client or httpx2.Client(timeout=10)
        self._url = url

    def advise(self, request: ProviderRouteRequest) -> ProviderRouteResult:
        retrieved_at = datetime.now(UTC)
        try:
            response = self._client.post(
                self._url,
                headers={"Authorization": self._api_key},
                json={
                    "coordinates": [
                        [request.origin.longitude, request.origin.latitude],
                        [request.destination.longitude, request.destination.latitude],
                    ],
                    "alternative_routes": {"target_count": 2, "weight_factor": 1.6},
                },
            )
        except httpx2.HTTPError:
            return self._suppressed("routing provider outage or network failure", retrieved_at)

        if response.status_code in {403, 429}:
            return self._suppressed("routing provider quota or access limit", retrieved_at)
        if response.status_code >= 500:
            return self._suppressed("routing provider outage", retrieved_at)
        if response.status_code == 404:
            return ProviderRouteResult(
                status=AdvisoryStatus.NO_ROUTE,
                reasons=(NO_ROUTE_REASON,),
                limitations=("The routing provider found no candidate route to validate.",),
                evidence=(),
                retrieved_at=retrieved_at,
            )
        if response.status_code >= 400:
            return self._suppressed("routing provider rejected the advisory request", retrieved_at)

        try:
            payload = response.json()
            feature = payload["features"][0]
            geometry = feature["geometry"]
            if geometry.get("type") not in {"LineString", "MultiLineString"}:
                raise ValueError("route response has no line geometry")
            shape(geometry)  # Validate the complete provider geometry before returning it.
        except (KeyError, IndexError, TypeError, ValueError):
            return self._suppressed("routing provider returned incomplete route geometry", retrieved_at)

        return ProviderRouteResult(
            status=AdvisoryStatus.ADVISORY,
            reasons=("route geometry returned by the approved routing provider",),
            limitations=("provider routing output is revalidated against official closures before display",),
            evidence=(),
            retrieved_at=retrieved_at,
            route_geometry=geometry,
        )

    @staticmethod
    def _suppressed(reason: str, retrieved_at: datetime) -> ProviderRouteResult:
        return ProviderRouteResult(
            status=AdvisoryStatus.SUPPRESSED,
            reasons=(reason,),
            limitations=("No route is published when the routing provider cannot be verified.",),
            evidence=(),
            retrieved_at=retrieved_at,
        )


class OfficialClosureGeometryValidator:
    """Reject a route when a verified official restriction cannot be cleared."""

    def validate(
        self, route_geometry: dict | None, restrictions: tuple[EvaluatedRestriction, ...]
    ) -> tuple[str, ...]:
        if route_geometry is None:
            return ("provider did not return complete route geometry",)
        try:
            route = shape(route_geometry)
            if route.is_empty:
                return ("provider returned an empty route geometry",)
        except (TypeError, ValueError, AttributeError):
            return ("provider route geometry could not be validated",)

        violations: list[str] = []
        for restriction in restrictions:
            if restriction.geometry is None:
                return (f"official restriction {restriction.native_id} has no geometry for validation",)
            try:
                if route.intersects(shape(restriction.geometry)):
                    violations.append(f"route intersects verified official restriction {restriction.native_id}")
            except (TypeError, ValueError, AttributeError):
                return (f"official restriction {restriction.native_id} geometry could not be validated",)
        return tuple(violations)


class VerifiedPublicAdvisoryService:
    """Publishes only a fresh, complete, revalidated public route advisory."""

    def __init__(
        self,
        provider: RouteAdvisoryProvider,
        geometry_validator: RouteGeometryValidator | None = None,
        policy_version: str = POLICY_VERSION,
        qualification_passed: bool = False,
    ) -> None:
        self._boundary = WayfinderBoundary(provider)
        self._geometry_validator = geometry_validator or OfficialClosureGeometryValidator()
        self._policy_version = policy_version
        self._qualification_passed = qualification_passed

    def advise(
        self,
        origin: Coordinate,
        destination: Coordinate,
        assessment: ClosureAssessment,
        checked_at: datetime,
    ) -> VerifiedAdvisory:
        restrictions = assessment.hard_restrictions
        restriction_ids = tuple(item.native_id for item in restrictions)
        source_urls = assessment.official_condition_links
        if not self._qualification_passed:
            return self._withheld(
                AdvisoryStatus.SUPPRESSED,
                ("approved routing provider has not passed the required RGV qualification suite",),
                source_urls,
                restriction_ids,
                checked_at,
                "provider qualification is not recorded as passed",
            )
        if not assessment.can_publish_route:
            return self._withheld(
                AdvisoryStatus.SUPPRESSED,
                assessment.limitations,
                source_urls,
                restriction_ids,
                checked_at,
                "official closure coverage is not current",
            )

        provider_advisory = self._boundary.public_advisory(origin, destination, restriction_ids)
        if provider_advisory.status == AdvisoryStatus.NO_ROUTE:
            no_route = RouteAdvisory(
                status=AdvisoryStatus.NO_ROUTE,
                reasons=(NO_ROUTE_REASON, *provider_advisory.reasons),
                limitations=provider_advisory.limitations,
                evidence=provider_advisory.evidence,
                retrieved_at=provider_advisory.retrieved_at,
                route_segment_ids=(),
                route_geometry=None,
            )
            return self._publish_with_provenance(
                self._add_limitations(no_route, source_urls),
                checked_at,
                "provider found no eligible candidate",
                restriction_ids,
                source_urls,
            )
        if provider_advisory.status != AdvisoryStatus.ADVISORY:
            return self._publish_with_provenance(
                self._add_limitations(provider_advisory, source_urls),
                checked_at,
                "provider did not produce an eligible advisory",
                restriction_ids,
                source_urls,
            )

        violations = self._geometry_validator.validate(provider_advisory.route_geometry, restrictions)
        if violations:
            return self._withheld(
                AdvisoryStatus.SUPPRESSED,
                violations,
                source_urls,
                restriction_ids,
                checked_at,
                "official overlay validation failed",
            )

        advisory = self._add_limitations(provider_advisory, source_urls)
        return self._publish_with_provenance(
            advisory, checked_at, "complete official overlay validation passed", restriction_ids, source_urls
        )

    def _withheld(
        self,
        status: AdvisoryStatus,
        reasons: tuple[str, ...],
        source_urls: tuple[str, ...],
        restriction_ids: tuple[str, ...],
        checked_at: datetime,
        validation_outcome: str,
    ) -> VerifiedAdvisory:
        advisory = RouteAdvisory(
            status=status,
            reasons=reasons or (NO_ROUTE_REASON,),
            limitations=(PUBLIC_LIMITATION, *tuple(f"Official conditions: {url}" for url in source_urls)),
            evidence=(),
            retrieved_at=checked_at,
            route_segment_ids=(),
            route_geometry=None,
        )
        return self._publish_with_provenance(advisory, checked_at, validation_outcome, restriction_ids, source_urls)

    def _add_limitations(self, advisory: RouteAdvisory, source_urls: tuple[str, ...]) -> RouteAdvisory:
        return RouteAdvisory(
            status=advisory.status,
            reasons=advisory.reasons,
            limitations=(*advisory.limitations, PUBLIC_LIMITATION, *(f"Official conditions: {url}" for url in source_urls)),
            evidence=advisory.evidence,
            retrieved_at=advisory.retrieved_at,
            route_segment_ids=advisory.route_segment_ids,
            route_geometry=advisory.route_geometry,
        )

    def _publish_with_provenance(
        self,
        advisory: RouteAdvisory,
        checked_at: datetime,
        validation_outcome: str,
        restriction_ids: tuple[str, ...],
        source_urls: tuple[str, ...],
    ) -> VerifiedAdvisory:
        return VerifiedAdvisory(
            advisory,
            AdvisoryProvenance(
                self._policy_version,
                checked_at,
                advisory.status,
                validation_outcome,
                restriction_ids,
                source_urls,
            ),
        )
