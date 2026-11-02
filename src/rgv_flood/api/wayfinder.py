"""Public, fail-closed Wayfinder advisory endpoint.

The browser sends only two coordinates.  Provider selection, credentials, and
vehicle profiles never cross this boundary; a route is returned only by the
already verified public-advisory service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from gzip import decompress
from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import MultiPoint, shape
from shapely.ops import unary_union

from rgv_flood.api.geocode import allow_client_geocoding
from rgv_flood.api.wayfinder_addresses import resolve_public_address
from rgv_flood.db import Database, Db
from rgv_flood.wayfinder import AdvisoryStatus, Coordinate, RouteAdvisory
from rgv_flood.wayfinder_advisories import (
    POLICY_VERSION,
    AdvisoryProvenance,
    OpenRouteServiceProvider,
    ProviderConfiguration,
    ProviderQualificationRecord,
    VerifiedAdvisory,
    VerifiedPublicAdvisoryService,
)
from rgv_flood.wayfinder_closures import (
    DRIVE_TEXAS_SOURCES,
    ClosureAssessment,
    ClosureEvidencePolicy,
    ClosureRecord,
    FeedCoverage,
    MatchBasis,
)
from rgv_flood.wayfinder_updates import (
    RefreshTrigger,
    RouteUpdateProposer,
    SoftRiskEvaluation,
    VerifiedAdvisoryReevaluation,
)

router = APIRouter()


def install(app) -> None:
    """Install the approved server-only adapter only with its recorded qualification.

    The qualification record is operational evidence, not something a public
    request can create or select.  An absent or malformed record deliberately
    leaves the endpoint in its explanatory suppressed state.
    """
    settings = app.state.settings
    secret = settings.wayfinder_ors_api_key
    if secret is None or not settings.wayfinder_qualification_record:
        return
    try:
        raw = json.loads(settings.wayfinder_qualification_record)
        qualified_at = _parse_time(raw["qualified_at"])
        expires_at = _parse_time(raw["expires_at"])
        if qualified_at is None or expires_at is None:
            return
        record = ProviderQualificationRecord(
            record_id=raw["record_id"],
            provider_configuration=ProviderConfiguration(**raw["provider_configuration"]),
            policy_version=raw["policy_version"], suite_version=raw["suite_version"],
            qualified_at=qualified_at, expires_at=expires_at,
            suite_case_ids=tuple(raw["suite_case_ids"]), failures=tuple(raw.get("failures", ())),
        )
        provider = OpenRouteServiceProvider(secret.get_secret_value())
        app.state.wayfinder_advisory_service = VerifiedPublicAdvisoryService(
            provider, policy_version=POLICY_VERSION, qualification_record=record
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return


class AdvisoryRequest(BaseModel):
    """The entire public input contract; coordinates and provider fields are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    origin: str = Field(max_length=160)
    destination: str = Field(max_length=160)


class RouteUpdateRequest(BaseModel):
    """An opaque active-advisory reference, not client-provided route state."""

    model_config = ConfigDict(extra="forbid")

    active_advisory_id: str = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class ActivePublicAdvisory:
    """Server-held context needed to justify a later route-update proposal."""

    origin: Coordinate
    destination: Coordinate
    restriction_ids: frozenset[str]
    checked_at: datetime


ACTIVE_ADVISORY_MAX_AGE = timedelta(minutes=5)


class AdvisoryService(Protocol):
    def advise(
        self, origin: Coordinate, destination: Coordinate, assessment: ClosureAssessment, checked_at: datetime
    ) -> VerifiedAdvisory: ...


@dataclass(frozen=True)
class DatabaseClosureAssessments:
    """Turn the latest stored official snapshots into one conservative assessment."""

    db: Database

    def assess(self, checked_at: datetime, corridor_geometry: dict | None) -> ClosureAssessment:
        corridor_covered = self._corridor_is_covered(corridor_geometry)
        coverage = tuple(self._coverage(source, corridor_covered) for source in DRIVE_TEXAS_SOURCES)
        records = tuple(self._records())
        return ClosureEvidencePolicy().assess(coverage, records, checked_at)


    def _coverage(self, source: str, corridor_covered: bool) -> FeedCoverage:
        row = self.db.rows(
            """select completed_at, is_complete, error_message from live_signal_runs
               where source = ? order by run_id desc limit 1""",
            (source,),
        )
        latest = row[0] if row else None
        return FeedCoverage(
            source=source,
            publisher="TxDOT",
            official_conditions_url="https://drivetexas.org/",
            completed_at=_parse_time(latest["completed_at"]) if latest else None,
            is_complete=bool(latest and latest["is_complete"]),
            retrieval_failure=latest["error_message"] if latest else "required official feed has no snapshot",
            corridor_covered=corridor_covered,
        )

    def _corridor_is_covered(self, corridor_geometry: dict | None) -> bool:
        """Require every displayed route coordinate to stay in the official area.

        DriveTexas ingestion is intentionally limited to the four RGV counties.
        Missing or malformed county geometry is therefore uncertainty, never a
        reason to publish a route based on a broader feed-wide freshness claim.
        """
        if corridor_geometry is None:
            return False
        try:
            corridor = shape(corridor_geometry)
            if corridor.is_empty:
                return False
            row = self.db.rows("select geojson_gzip from layers where id = ?", ("county-boundaries",))
            if not row or not row[0]["geojson_gzip"]:
                return False
            collection = json.loads(decompress(row[0]["geojson_gzip"]).decode("utf-8"))
            boundaries = [
                shape(feature["geometry"])
                for feature in collection.get("features", ())
                if feature.get("geometry")
            ]
            area = unary_union(boundaries)
            return not area.is_empty and area.covers(corridor)
        except (TypeError, ValueError, KeyError, UnicodeDecodeError, OSError, json.JSONDecodeError):
            return False

    def _records(self):
        rows = self.db.rows(
            """select source, native_id, source_url, source_publisher, retrieved_at,
                      source_geometry_json, source_attributes_json
                 from live_signals
                where lifecycle_state = 'active' and provenance = 'official'
                  and source in (?, ?)""",
            DRIVE_TEXAS_SOURCES,
        ) or []
        for row in rows:
            retrieved_at = _parse_time(row["retrieved_at"])
            if retrieved_at is None:
                continue
            try:
                geometry = json.loads(row["source_geometry_json"])
                attributes = json.loads(row["source_attributes_json"])
            except (TypeError, json.JSONDecodeError):
                # Keep malformed official evidence out of a positive decision;
                # missing coverage below already suppresses publication.
                continue
            yield ClosureRecord(
                source=row["source"], native_id=row["native_id"], source_url=row["source_url"],
                publisher=row["source_publisher"], retrieved_at=retrieved_at, geometry=geometry,
                attributes=attributes, match_basis=MatchBasis.CONSERVATIVE_ROUTE_MATCH,
            )


@dataclass(frozen=True)
class CurrentDatabaseClosureAssessments:
    """Provider-bound reevaluation source for one requested advisory corridor."""

    assessments: DatabaseClosureAssessments
    endpoint_corridor: dict

    def assess_current(self, checked_at: datetime) -> ClosureAssessment:
        return self.assessments.assess(checked_at, self.endpoint_corridor)


class _UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _withheld(assessment: ClosureAssessment, checked_at: datetime, reason: str) -> VerifiedAdvisory:
    advisory = RouteAdvisory(
        status=AdvisoryStatus.SUPPRESSED,
        reasons=(reason,), limitations=assessment.limitations or (reason,), evidence=(),
        retrieved_at=checked_at, route_segment_ids=(), route_geometry=None,
    )
    return VerifiedAdvisory(advisory, AdvisoryProvenance(
        policy_version=POLICY_VERSION, checked_at=checked_at,
        provider_status=AdvisoryStatus.SUPPRESSED, validation_outcome=reason,
        restriction_ids=(), source_urls=assessment.official_condition_links,
        qualification_record_id=None, qualification_suite_version=None,
    ))


def _response(result: VerifiedAdvisory, assessment: ClosureAssessment) -> dict:
    advisory, provenance = result.advisory, result.provenance
    body = {
        "status": advisory.status, "reasons": list(advisory.reasons),
        "limitations": list(advisory.limitations), "last_checked": provenance.checked_at,
        "official_condition_links": list(provenance.source_urls),
        "applied_restrictions": list(provenance.restriction_ids),
        "cautions": [item.limitation or item.native_id for item in assessment.cautions],
        "policy_version": provenance.policy_version, "validation_outcome": provenance.validation_outcome,
        "geometry": None,
    }
    if advisory.status is AdvisoryStatus.ADVISORY:
        body["geometry"] = advisory.route_geometry
    return body


def _endpoint_corridor(origin: Coordinate, destination: Coordinate) -> dict:
    return MultiPoint(
        [(origin.longitude, origin.latitude), (destination.longitude, destination.latitude)]
    ).__geo_interface__


def _active_advisories(request: Request) -> dict[str, ActivePublicAdvisory]:
    """Return process-held advisory context; clients never supply this evidence."""
    registry = getattr(request.app.state, "wayfinder_active_advisories", None)
    if registry is None:
        registry = {}
        request.app.state.wayfinder_active_advisories = registry
    return registry


def _restriction_ids(assessment: ClosureAssessment) -> frozenset[str]:
    return frozenset(item.native_id for item in assessment.hard_restrictions)


def _verified_trigger(
    active: ActivePublicAdvisory, assessment: ClosureAssessment, checked_at: datetime
) -> tuple[RefreshTrigger, tuple[str, ...]] | None:
    """Derive an update reason only from the active record and official state.

    The service currently holds official restriction snapshots and advisory
    timestamps, but not a traveler location or a traffic/soft-risk feed.  Those
    unavailable sources deliberately cannot manufacture departure or risk
    triggers.  A future server-side source can extend this one owner.
    """
    current_restrictions = _restriction_ids(assessment)
    if current_restrictions != active.restriction_ids:
        expired = active.restriction_ids - current_restrictions
        added = current_restrictions - active.restriction_ids
        if expired and not added:
            return (
                RefreshTrigger.RESTRICTION_EXPIRED,
                (
                    "official restriction set expired since the active advisory",
                    *tuple(sorted(expired)),
                ),
            )
        return (
            RefreshTrigger.RESTRICTION_CHANGED,
            (
                "official restriction set changed since the active advisory",
                *tuple(sorted(added | expired)),
            ),
        )
    if checked_at - active.checked_at >= ACTIVE_ADVISORY_MAX_AGE:
        return (
            RefreshTrigger.TRAFFIC_ETA_EXPIRED,
            ("active advisory traffic and ETA evidence exceeded its freshness window",),
        )
    return None


def _proposal_response(proposal, event, assessment: ClosureAssessment, trigger_evidence: tuple[str, ...] = ()) -> dict:
    """Keep the candidate separate so clients cannot mistake it for an active route."""
    if proposal is None:
        return {
            "proposal": None,
            "outcome": event.user_visible_result,
            "cautions": [item.limitation or item.native_id for item in assessment.cautions],
        }
    result = _response(proposal.advisory, assessment)
    return {
        "proposal": {
            "active_advisory_id": proposal.active_advisory_id,
            "trigger": proposal.trigger,
            "message": proposal.public_message,
            "reasons": list(proposal.reasons),
            "limitations": list(proposal.limitations),
            "policy_versions": list(event.policy_versions),
            "evidence_ids": list(event.evidence_ids),
            "trigger_evidence": list(trigger_evidence),
            "advisory": result,
        },
        "outcome": event.user_visible_result,
        "cautions": [item.limitation or item.native_id for item in assessment.cautions],
    }


@router.post("/wayfinder/advisories")
def public_advisory(payload: AdvisoryRequest, request: Request, db: Db):
    """Return an advisory or an explanatory safe failure, never a raw provider result."""
    checked_at = datetime.now(UTC)
    assessments = DatabaseClosureAssessments(db)
    # An advisory may resolve two addresses, but it consumes one bounded public
    # geocoding operation.  Reserve it before either lookup, even while the
    # advisory provider is unconfigured, so this endpoint cannot bypass the
    # provider-use policy or start an upstream lookup after the limit is hit.
    if not allow_client_geocoding(request):
        assessment = assessments.assess(checked_at, None)
        result = _withheld(
            assessment,
            checked_at,
            "Wayfinder address resolution is temporarily limited. Try again in a minute.",
        )
        return _response(result, assessment)
    origin = resolve_public_address(getattr(request.app.state, "geocoder", None), payload.origin, "Origin")
    destination = resolve_public_address(getattr(request.app.state, "geocoder", None), payload.destination, "Destination")
    if origin.coordinate is None or destination.coordinate is None:
        assessment = assessments.assess(checked_at, None)
        reason = origin.reason if origin.coordinate is None else destination.reason
        result = _withheld(assessment, checked_at, reason or "Wayfinder address resolution could not be verified.")
        return _response(result, assessment)

    assessment = assessments.assess(checked_at, _endpoint_corridor(origin.coordinate, destination.coordinate))
    service = getattr(request.app.state, "wayfinder_advisory_service", None)
    if service is None:
        result = _withheld(assessment, checked_at, "Wayfinder advisory is not currently configured for public use.")
    elif not assessment.can_publish_route:
        result = _withheld(assessment, checked_at, "Official closure coverage cannot validate the requested route corridor.")
    else:
        result = service.advise(origin.coordinate, destination.coordinate, assessment, checked_at)
        if result.advisory.status is AdvisoryStatus.ADVISORY:
            assessment = assessments.assess(checked_at, result.advisory.route_geometry)
            if not assessment.can_publish_route:
                result = _withheld(assessment, checked_at, "Official closure coverage cannot validate the returned route corridor.")
    body = _response(result, assessment)
    if result.advisory.status is AdvisoryStatus.ADVISORY:
        advisory_id = str(uuid4())
        _active_advisories(request)[advisory_id] = ActivePublicAdvisory(
            origin.coordinate, destination.coordinate, _restriction_ids(assessment), checked_at
        )
        body["advisory_id"] = advisory_id
    return body


@router.post("/wayfinder/advisories/updates")
def propose_public_advisory_update(payload: RouteUpdateRequest, request: Request, db: Db):
    """Return a reviewable route update only after a complete fresh reevaluation.

    This endpoint deliberately has no accept/activate operation.  A proposal is
    rendered beside the active advisory and the browser must explicitly decide
    whether to draw it.
    """
    assessments = DatabaseClosureAssessments(db)
    checked_at = datetime.now(UTC)
    active = _active_advisories(request).get(payload.active_advisory_id)
    if active is None:
        return {
            "proposal": None,
            "outcome": "No route update is proposed because the active advisory is not held by this server.",
            "cautions": [],
        }
    endpoint_corridor = MultiPoint(
        [(active.origin.longitude, active.origin.latitude), (active.destination.longitude, active.destination.latitude)]
    ).__geo_interface__
    assessment = assessments.assess(checked_at, endpoint_corridor)
    service = getattr(request.app.state, "wayfinder_advisory_service", None)
    if not isinstance(service, VerifiedPublicAdvisoryService) or not assessment.can_publish_route:
        # The standard public endpoint produces the canonical explanatory
        # suppression response.  Route updates add no alternate success path.
        withheld = _withheld(assessment, checked_at, "Current conditions cannot produce a verified route update.")
        return {
            "proposal": None,
            "outcome": "No route update is proposed because current reevaluation could not be verified.",
            "cautions": [item.limitation or item.native_id for item in assessment.cautions],
            "validation_outcome": withheld.provenance.validation_outcome,
        }

    trigger = _verified_trigger(active, assessment, checked_at)
    if trigger is None:
        return {
            "proposal": None,
            "outcome": "No route update is proposed because no server-verified reevaluation trigger is current.",
            "cautions": [item.limitation or item.native_id for item in assessment.cautions],
        }
    verified_trigger, trigger_evidence = trigger

    reevaluation = VerifiedAdvisoryReevaluation(
        service,
        CurrentDatabaseClosureAssessments(assessments, endpoint_corridor),
        active.origin, active.destination, _UtcClock(),
    )
    proposal, event = RouteUpdateProposer(reevaluation).propose(
        active_advisory_id=payload.active_advisory_id,
        trigger=verified_trigger,
        risk_evaluation=SoftRiskEvaluation((), (), False),
    )
    # A provider can return a geometry that does not match the endpoint chord.
    # Re-check its entire shape before allowing even a visible candidate.
    if proposal is not None:
        assessment = assessments.assess(checked_at, proposal.advisory.advisory.route_geometry)
        if not assessment.can_publish_route:
            proposal = None
            event = event.__class__(
                event.trigger, event.policy_versions, event.evidence_ids,
                (*event.match_reasons, "returned route corridor lacks complete official coverage"),
                event.provider_status, "returned route corridor lacks complete official coverage",
                event.validation_record,
                "No route update is proposed because current reevaluation could not be verified.",
            )
    return _proposal_response(proposal, event, assessment, trigger_evidence)
