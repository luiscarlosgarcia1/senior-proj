"""Map page side panel: live alerts, flood events and their detail, rainfall, reports, sources."""

import json

from browser_support import wait_js
from playwright.sync_api import expect

SIGNALS = {
    "refreshed_at": "2026-10-15T10:15:04Z",
    "signals": [{
        "source": "nws", "native_id": "w-1", "source_url": "https://example.test/w-1",
        "source_publisher": "National Weather Service", "source_channel": "api", "summary": "Flash Flood Warning",
        "county_slugs": ["hidalgo"], "is_mappable": True, "geometry_absence_reason": None, "published_at": None,
        "effective_at": None, "source_updated_at": None, "expires_at": "2026-10-15T23:45:00Z",
        "last_seen_at": "2026-10-15T10:15:00Z", "retrieved_at": "2026-10-15T10:15:00Z",
    }],
}


def test_alert_panel_empty_state(map_page):
    page = map_page()
    alerts = page.locator("[data-panel=alerts]")

    expect(alerts).to_contain_text("No active official alerts")
    expect(alerts).to_contain_text("Not refreshed yet")
    expect(page.locator("header")).to_contain_text("0 active alerts")


def test_alert_panel_lists_signals(page, live_server):
    page.route("**/api/v1/live-signals?**", lambda route: route.fulfill(json=SIGNALS))
    page.route("**/api/v1/live-signals", lambda route: route.fulfill(json=SIGNALS))
    page.goto(f"{live_server}/?test=1")

    alerts = page.locator("[data-panel=alerts]")
    expect(alerts).to_contain_text("Flash Flood Warning")
    expect(alerts).to_contain_text("National Weather Service")
    expect(page.locator("header")).to_contain_text("1 active alerts")


def test_event_chip_filters_list(map_page):
    page = map_page()
    events = page.locator("[data-panel=events] [data-event]")

    expect(events).to_have_count(2)
    page.locator("[data-panel=events] [data-chip='Flash flood']").click()
    expect(events).to_have_count(1)
    expect(events.first).to_contain_text("Flash flood")
    page.locator("[data-panel=events] [data-chip='2018']").click()
    expect(events).to_have_count(1)
    expect(events.first).to_contain_text("2018")
    page.locator("[data-panel=events] [data-chip='']").click()
    expect(events).to_have_count(2)


def test_select_event_fills_detail(map_page):
    page = map_page()

    page.locator("[data-event='noaa-storm-events-1']").click()

    detail = page.locator("[data-event-detail]")
    expect(detail).to_contain_text("Flash flood")
    expect(detail.locator("[data-gauge]").first).to_contain_text("McAllen Airport")
    expect(detail.locator("[data-gauge]").first).to_contain_text("1.00")
    detail.locator("[data-view-table]").click()
    expect(detail.locator("table th")).to_have_text(["Gauge", "Jul 24", "Jul 25", "Jul 26"])
    expect(detail).to_contain_text("Headline of hanna-landfall.")  # curated report
    expect(detail).to_contain_text("Streets flooded.")  # NWS report the same day
    wait_js(page, "window.__rgvMap.getSource('selection') !== undefined")


def test_county_change_refetches_panels(map_page):
    page = map_page()
    expect(page.locator("[data-panel=events] [data-event]")).to_have_count(2)

    page.locator("#county-header").select_option("cameron")

    expect(page.locator("[data-panel=events] [data-event]")).to_have_count(0)
    expect(page.locator("[data-panel=events]")).to_contain_text("No events match")
    expect(page.locator("[data-panel=reports]")).to_contain_text("No local reports")


def test_rainfall_records_ranked(map_page):
    page = map_page()
    records = page.locator("[data-panel=rainfall] [data-record]")

    expect(records.first).to_contain_text("Weslaco")
    expect(records.first).to_contain_text("8.6")


def test_sources_show_build_date(map_page):
    page = map_page()
    sources = page.locator("[data-panel=sources]")

    expect(sources).to_contain_text("Data built Oct 15, 2026")
    expect(sources).to_contain_text("Storm Events Database")


def test_signals_fixture_is_valid_json():
    json.dumps(SIGNALS)
