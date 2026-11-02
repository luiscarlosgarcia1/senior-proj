"""Public, fail-closed Wayfinder advisory endpoint.

The browser sends only two coordinates.  Provider selection, credentials, and
vehicle profiles never cross this boundary; a route is returned only by the
already verified public-advisory service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from gzip import decompress
from math import isfinite
from typing import Protocol

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import MultiPoint, shape
from shapely.ops import unary_union

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


class Waypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def finite(self) -> Waypoint:
        if not isfinite(self.latitude) or not isfinite(self.longitude):
            raise ValueError("coordinates must be finite")
        return self

    def coordinate(self) -> Coordinate:
        return Coordinate(self.latitude, self.longitude)


class AdvisoryRequest(BaseModel):
    """The entire public input contract; provider fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    origin: Waypoint
    destination: Waypoint


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


@router.post("/wayfinder/advisories")
def public_advisory(payload: AdvisoryRequest, request: Request, db: Db):
    """Return an advisory or an explanatory safe failure, never a raw provider result."""
    checked_at = datetime.now(UTC)
    assessments = DatabaseClosureAssessments(db)
    endpoint_corridor = MultiPoint(
        [(payload.origin.longitude, payload.origin.latitude), (payload.destination.longitude, payload.destination.latitude)]
    )
    assessment = assessments.assess(checked_at, endpoint_corridor.__geo_interface__)
    service = getattr(request.app.state, "wayfinder_advisory_service", None)
    if service is None:
        result = _withheld(assessment, checked_at, "Wayfinder advisory is not currently configured for public use.")
    elif not assessment.can_publish_route:
        result = _withheld(assessment, checked_at, "Official closure coverage cannot validate the requested route corridor.")
    else:
        result = service.advise(payload.origin.coordinate(), payload.destination.coordinate(), assessment, checked_at)
        if result.advisory.status is AdvisoryStatus.ADVISORY:
            assessment = assessments.assess(checked_at, result.advisory.route_geometry)
            if not assessment.can_publish_route:
                result = _withheld(assessment, checked_at, "Official closure coverage cannot validate the returned route corridor.")
    return _response(result, assessment)
