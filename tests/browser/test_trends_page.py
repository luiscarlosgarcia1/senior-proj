"""Trends: rain by year and month, flood events, NWS reports and news, per county and gauge."""

from browser_support import wait_js
from playwright.sync_api import expect

CHARTS = ["rain", "wettest", "over2", "months", "events", "nws", "news"]


def _open(page, live_server):
    page.goto(f"{live_server}/trends")
    wait_js(page, f"document.querySelectorAll('[data-chart].js-plotly-plot').length === {len(CHARTS)}")
    return page


def test_trends_page_draws_every_chart(page, live_server, console_errors):
    _open(page, live_server)

    expect(page.locator("[data-chart-title]")).to_have_count(len(CHARTS))
    assert page.evaluate("document.querySelector('[data-chart=events]').data.length") == 2  # Flash flood, Flood
    assert page.evaluate("document.querySelector('[data-chart=news]').data[0].y.reduce((a, b) => a + b, 0)") == 3
    assert console_errors == []


def test_county_switch_updates_the_series(page, live_server):
    _open(page, live_server)
    events_tile = page.locator("[data-tile=events] [data-value]")
    expect(events_tile).to_have_text("2")

    page.locator("#county-trends").select_option("cameron")

    expect(events_tile).to_have_text("0")
    expect(page.locator("[data-tile=news] [data-value]")).to_have_text("1")
    expect(page.locator("[data-no-rain]")).to_be_visible()  # Cameron has no gauges in the fixture


def test_gauge_select_narrows_to_one_gauge_and_resets_with_the_county(page, live_server):
    _open(page, live_server)
    gauges = page.locator("#gauge-trends")
    expect(gauges.locator("option")).to_have_text(["All gauges", "McAllen Airport", "Rio Grande City", "Weslaco"])

    gauges.select_option("USC00419588")  # Weslaco

    wait_js(page, "document.querySelector('[data-chart=rain]').data[0].y.length === 1")
    assert page.evaluate("document.querySelector('[data-chart=rain]').data[0].y[0]") == 10.0

    page.locator("#county-trends").select_option("starr")

    expect(gauges).to_have_value("")  # Weslaco isn't in Starr County


def test_view_table_toggle_shows_the_years(page, live_server):
    _open(page, live_server)

    page.locator("[data-view-table][data-for=events]").click()

    rows = page.locator("[data-chart-card=events] tbody tr")
    expect(rows.first).to_contain_text(str(page.evaluate("new Date().getUTCFullYear() - 1")))
    expect(page.locator("[data-chart-card=events] tbody")).to_contain_text("2020")


def test_page_links_to_claims_for_insurance(page, live_server):
    _open(page, live_server)

    expect(page.locator("[data-claims-link]")).to_have_attribute("href", "/claims")
