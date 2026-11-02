import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from rgv_flood.api.models import Place
from rgv_flood.wayfinder import AdvisoryStatus, RouteAdvisory
from rgv_flood.wayfinder_advisories import (
    AdvisoryProvenance,
    VerifiedAdvisory,
    VerifiedPublicAdvisoryService,
)

NOW = datetime(2026, 11, 2, 18, tzinfo=UTC)
ROUTE = {"type": "LineString", "coordinates": [[-98.2, 26.2], [-98.1, 26.3]]}
PAYLOAD = {"origin": "1200 W University Dr, Edinburg, TX", "destination": "100 E Expressway 83, McAllen, TX"}
OUTSIDE_ADDRESS = "1 Main St, Houston, TX"


class _AddressGeocoder:
    def __init__(self, places=None):
        self.places = places or {
            PAYLOAD["origin"]: [Place(label=PAYLOAD["origin"], lat=26.2, lon=-98.2)],
            PAYLOAD["destination"]: [Place(label=PAYLOAD["destination"], lat=26.3, lon=-98.1)],
            OUTSIDE_ADDRESS: [Place(label=OUTSIDE_ADDRESS, lat=29.8, lon=-95.4)],
        }

    def search(self, query):
        return self.places.get(query, [])


@pytest.fixture(autouse=True)
def _server_held_address_geocoder(api_client):
    api_client.app.state.geocoder = _AddressGeocoder()


class _Service:
    def advise(self, origin, destination, assessment, checked_at):
        advisory = RouteAdvisory(
            AdvisoryStatus.ADVISORY, ("validated provider route",),
            ("This advisory avoids currently reported fresh official closures; it does not confirm that roads are safe, open, or passable.",),
            (), checked_at, (), ROUTE,
        )
        return VerifiedAdvisory(advisory, AdvisoryProvenance(
            "wayfinder-public-closure-avoidance/v1", checked_at, AdvisoryStatus.ADVISORY,
            "complete official overlay validation passed", ("closure-1",), ("https://example.test/conditions",),
            "qualification-1", "rgv-provider-qualification/v1",
        ))


class _LeavingAreaService(_Service):
    def advise(self, origin, destination, assessment, checked_at):
        result = super().advise(origin, destination, assessment, checked_at)
        route = RouteAdvisory(
            result.advisory.status, result.advisory.reasons, result.advisory.limitations,
            result.advisory.evidence, result.advisory.retrieved_at, result.advisory.route_segment_ids,
            {"type": "LineString", "coordinates": [[-98.2, 26.2], [-100.0, 26.3]]},
        )
        return VerifiedAdvisory(route, result.provenance)


class _VerifiedService(_Service, VerifiedPublicAdvisoryService):
    """An API fixture that still satisfies the concrete reevaluation boundary."""


class _StaleVerifiedService(_VerifiedService):
    def advise(self, origin, destination, assessment, checked_at):
        result = super().advise(origin, destination, assessment, checked_at)
        stale = RouteAdvisory(
            result.advisory.status, result.advisory.reasons, result.advisory.limitations,
            result.advisory.evidence, checked_at - timedelta(minutes=1), result.advisory.route_segment_ids,
            result.advisory.route_geometry,
        )
        return VerifiedAdvisory(stale, AdvisoryProvenance(
            result.provenance.policy_version, checked_at - timedelta(minutes=1), result.provenance.provider_status,
            result.provenance.validation_outcome, result.provenance.restriction_ids, result.provenance.source_urls,
            result.provenance.qualification_record_id, result.provenance.qualification_suite_version,
        ))


def _record_current_official_coverage(api_client):
    """Give the fixture a fresh completed DriveTexas run for each required feed."""
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(api_client.app.state.settings.database) as connection:
        connection.executemany(
            """insert into live_signal_runs
               (source, retrieved_at, completed_at, is_complete, received_count, error_message)
               values (?, ?, ?, 1, 0, null)""",
            [("drivetexas:points", now, now), ("drivetexas:lines", now, now)],
        )


def test_wayfinder_returns_only_a_validated_public_route_shape(api_client):
    _record_current_official_coverage(api_client)
    api_client.app.state.wayfinder_advisory_service = _Service()

    response = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "advisory", "reasons": ["validated provider route"],
        "limitations": ["This advisory avoids currently reported fresh official closures; it does not confirm that roads are safe, open, or passable."],
        "last_checked": response.json()["last_checked"], "official_condition_links": ["https://example.test/conditions"],
        "applied_restrictions": ["closure-1"], "cautions": [],
        "policy_version": "wayfinder-public-closure-avoidance/v1",
        "validation_outcome": "complete official overlay validation passed", "geometry": ROUTE,
        "advisory_id": body["advisory_id"],
    }


def test_wayfinder_is_suppressed_without_server_only_approved_configuration(api_client):
    response = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["status"] == "suppressed"
    assert response.json()["geometry"] is None
    assert "not currently configured" in response.json()["reasons"][0]


def test_wayfinder_rejects_provider_and_profile_fields_from_public_requests(api_client):
    response = api_client.post("/api/v1/wayfinder/advisories", json={**PAYLOAD, "profile": "responder", "api_key": "leak"})

    assert response.status_code == 422


def test_wayfinder_rejects_client_supplied_coordinates(api_client):
    response = api_client.post("/api/v1/wayfinder/advisories", json={
        "origin": {"latitude": 26.2, "longitude": -98.2},
        "destination": {"latitude": 26.3, "longitude": -98.1},
    })

    assert response.status_code == 422


def test_wayfinder_suppresses_an_unresolved_or_ambiguous_address(api_client):
    api_client.app.state.geocoder = _AddressGeocoder({
        PAYLOAD["origin"]: [Place(label=PAYLOAD["origin"], lat=26.2, lon=-98.2)],
        "Ambiguous Ave": [
            Place(label="Ambiguous Ave A", lat=26.3, lon=-98.1),
            Place(label="Ambiguous Ave B", lat=26.31, lon=-98.11),
        ],
    })

    unresolved = api_client.post("/api/v1/wayfinder/advisories", json={**PAYLOAD, "destination": "Unknown Lane"})
    ambiguous = api_client.post("/api/v1/wayfinder/advisories", json={**PAYLOAD, "destination": "Ambiguous Ave"})

    assert unresolved.status_code == ambiguous.status_code == 200
    assert unresolved.json()["status"] == ambiguous.json()["status"] == "suppressed"
    assert unresolved.json()["geometry"] is ambiguous.json()["geometry"] is None
    assert "could not be resolved" in unresolved.json()["reasons"][0]
    assert "ambiguous" in ambiguous.json()["reasons"][0]


def test_wayfinder_suppresses_blank_addresses_without_geometry(api_client):
    response = api_client.post("/api/v1/wayfinder/advisories", json={**PAYLOAD, "origin": "  "})

    assert response.status_code == 200
    assert response.json()["status"] == "suppressed"
    assert response.json()["geometry"] is None
    assert "not a usable street address" in response.json()["reasons"][0]


def test_wayfinder_suppresses_an_out_of_area_endpoint_even_with_fresh_feeds(api_client):
    _record_current_official_coverage(api_client)
    api_client.app.state.wayfinder_advisory_service = _Service()

    response = api_client.post("/api/v1/wayfinder/advisories", json={
        "origin": PAYLOAD["origin"],
        "destination": OUTSIDE_ADDRESS,
    })

    assert response.status_code == 200
    assert response.json()["status"] == "suppressed"
    assert response.json()["geometry"] is None
    assert "cannot validate the requested route corridor" in response.json()["reasons"][0]


def test_wayfinder_suppresses_a_returned_route_that_leaves_official_coverage(api_client):
    _record_current_official_coverage(api_client)
    api_client.app.state.wayfinder_advisory_service = _LeavingAreaService()

    response = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["status"] == "suppressed"
    assert response.json()["geometry"] is None
    assert "cannot validate the returned route corridor" in response.json()["reasons"][0]


def test_wayfinder_returns_a_separate_verified_update_proposal(api_client):
    _record_current_official_coverage(api_client)
    api_client.app.state.wayfinder_advisory_service = _VerifiedService.__new__(_VerifiedService)

    active = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD).json()
    advisory_id = active["advisory_id"]
    stored = api_client.app.state.wayfinder_active_advisories[advisory_id]
    api_client.app.state.wayfinder_active_advisories[advisory_id] = replace(
        stored, checked_at=stored.checked_at - timedelta(minutes=6)
    )
    response = api_client.post("/api/v1/wayfinder/advisories/updates", json={"active_advisory_id": advisory_id})

    assert response.status_code == 200
    proposal = response.json()["proposal"]
    assert proposal["active_advisory_id"] == advisory_id
    assert proposal["trigger"] == "traffic_eta_expired"
    assert proposal["trigger_evidence"] == ["active advisory traffic and ETA evidence exceeded its freshness window"]
    assert proposal["advisory"]["geometry"] == ROUTE
    assert "not replaced" in proposal["message"]


def test_wayfinder_stale_reevaluation_cannot_produce_a_proposal(api_client):
    _record_current_official_coverage(api_client)
    api_client.app.state.wayfinder_advisory_service = _StaleVerifiedService.__new__(_StaleVerifiedService)

    active = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD).json()
    advisory_id = active["advisory_id"]
    stored = api_client.app.state.wayfinder_active_advisories[advisory_id]
    api_client.app.state.wayfinder_active_advisories[advisory_id] = replace(
        stored, checked_at=stored.checked_at - timedelta(minutes=6)
    )
    response = api_client.post("/api/v1/wayfinder/advisories/updates", json={"active_advisory_id": advisory_id})

    assert response.status_code == 200
    assert response.json()["proposal"] is None
    assert "could not be verified" in response.json()["outcome"]


def test_wayfinder_rejects_a_client_declared_update_trigger(api_client):
    response = api_client.post("/api/v1/wayfinder/advisories/updates", json={
        **PAYLOAD, "active_advisory_id": "fabricated", "trigger": "restriction_changed",
    })

    assert response.status_code == 422


def test_wayfinder_does_not_propose_without_server_held_trigger_evidence(api_client):
    _record_current_official_coverage(api_client)
    api_client.app.state.wayfinder_advisory_service = _VerifiedService.__new__(_VerifiedService)

    active = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD).json()
    response = api_client.post(
        "/api/v1/wayfinder/advisories/updates", json={"active_advisory_id": active["advisory_id"]}
    )

    assert response.status_code == 200
    assert response.json()["proposal"] is None
    assert "no server-verified" in response.json()["outcome"]
