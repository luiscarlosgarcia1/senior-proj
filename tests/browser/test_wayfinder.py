"""Browser behavior for the public, address-based Wayfinder form."""

from playwright.sync_api import expect


def test_wayfinder_submits_addresses_without_coordinates(map_page):
    page = map_page()
    requests = []

    def advisory(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json={
            "status": "advisory",
            "reasons": ["validated provider route"],
            "limitations": ["This is an advisory, not a safety or passability claim."],
            "last_checked": "2026-11-02T18:00:00Z",
            "official_condition_links": ["https://example.test/conditions"],
            "applied_restrictions": [], "cautions": [],
            "policy_version": "wayfinder-public-closure-avoidance/v1",
            "validation_outcome": "complete official overlay validation passed",
            "geometry": {"type": "LineString", "coordinates": [[-98.2, 26.2], [-98.1, 26.3]]},
            "advisory_id": "address-advisory-1",
        })

    page.route("**/api/v1/wayfinder/advisories", advisory)
    page.locator("[data-wayfinder-form] [name=origin]").fill("1200 W University Dr, Edinburg, TX")
    page.locator("[data-wayfinder-form] [name=destination]").fill("100 E Expressway 83, McAllen, TX")
    page.locator("[data-wayfinder-form]").press("Enter")

    expect(page.locator("[data-wayfinder-active]")).to_contain_text("Active advisory")
    assert requests == [{
        "origin": "1200 W University Dr, Edinburg, TX",
        "destination": "100 E Expressway 83, McAllen, TX",
    }]
