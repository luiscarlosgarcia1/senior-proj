from datetime import UTC, datetime

from rgv_flood.wayfinder import AdvisoryStatus, RouteAdvisory
from rgv_flood.wayfinder_advisories import AdvisoryProvenance, VerifiedAdvisory

NOW = datetime(2026, 11, 2, 18, tzinfo=UTC)
ROUTE = {"type": "LineString", "coordinates": [[-98.2, 26.2], [-98.1, 26.3]]}
PAYLOAD = {"origin": {"latitude": 26.2, "longitude": -98.2}, "destination": {"latitude": 26.3, "longitude": -98.1}}


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


def test_wayfinder_returns_only_a_validated_public_route_shape(api_client):
    api_client.app.state.wayfinder_advisory_service = _Service()

    response = api_client.post("/api/v1/wayfinder/advisories", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json() == {
        "status": "advisory", "reasons": ["validated provider route"],
        "limitations": ["This advisory avoids currently reported fresh official closures; it does not confirm that roads are safe, open, or passable."],
        "last_checked": response.json()["last_checked"], "official_condition_links": ["https://example.test/conditions"],
        "applied_restrictions": ["closure-1"], "cautions": [],
        "policy_version": "wayfinder-public-closure-avoidance/v1",
        "validation_outcome": "complete official overlay validation passed", "geometry": ROUTE,
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
