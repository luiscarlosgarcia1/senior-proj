"""Claims & rainfall by year: tiles, three Plotly charts, the year table."""

from browser_support import wait_js
from playwright.sync_api import expect


def _open(page, live_server):
    page.goto(f"{live_server}/claims")
    wait_js(page, "document.querySelectorAll('[data-chart].js-plotly-plot').length === 3")
    return page


def test_claims_page_draws_three_charts(page, live_server, console_errors):
    _open(page, live_server)

    titles = page.locator("[data-chart-title]")
    expect(titles).to_have_text(["Flood insurance claims", "Yearly rain", "Wettest day of the year"])
    bars = page.evaluate("document.querySelector('[data-chart=claims]').data[0].y.length")
    assert bars == page.evaluate("new Date().getUTCFullYear() - 1978")  # 1978 .. last full year
    assert console_errors == []


def test_metric_switch_changes_first_chart_title(page, live_server):
    _open(page, live_server)

    page.locator("[data-metric=paid]").click()

    expect(page.locator("[data-chart-title]").first).to_have_text("Dollars paid on claims")
    # 2020: $1,000 + $500 in Hidalgo and $250 in Starr
    wait_js(page, "Math.max(...document.querySelector('[data-chart=claims]').data[0].y) === 1750")


def test_county_switch_updates_tiles(page, live_server):
    _open(page, live_server)
    claims_tile = page.locator("[data-tile=claims] [data-value]")
    expect(claims_tile).to_have_text("4")

    page.locator("#county-claims").select_option("starr")

    expect(claims_tile).to_have_text("1")
    expect(page.locator("[data-tile=worst] [data-value]")).to_have_text("2020")


def test_hover_highlights_table_row(page, live_server):
    _open(page, live_server)
    box = page.locator("[data-chart=claims]").bounding_box()
    x, y = page.evaluate("""(() => {
      const layout = document.querySelector('[data-chart=claims]')._fullLayout;
      return [layout.margin.l + layout.xaxis.l2p(2020), layout.margin.t + layout.yaxis._length - 4];
    })()""")

    page.mouse.move(box["x"] + x, box["y"] + y)

    expect(page.locator("tr.is-selected")).to_have_count(1)
    expect(page.locator("tr.is-selected td").first).to_have_text("2020")


def test_charts_follow_theme(page, live_server):
    _open(page, live_server)
    before = page.evaluate("document.querySelector('[data-chart=claims]').data[0].marker.color")

    page.locator("header label:has-text('Dark') input").click()  # flip whichever theme it started in

    wait_js(page, f"document.querySelector('[data-chart=claims]').data[0].marker.color !== {before!r}")


def test_view_as_table_toggle(page, live_server):
    _open(page, live_server)
    card = page.locator("[data-chart-card=rain]")

    card.locator("[data-view-table]").click()

    expect(card.locator("table")).to_be_visible()
    expect(card.locator("[data-chart]")).to_be_hidden()
    expect(card.locator("table tbody tr").first).to_contain_text("2025")


def test_annotates_hanna(page, live_server):
    _open(page, live_server)

    texts = page.evaluate("document.querySelector('[data-chart=claims]').layout.annotations.map(a => a.text)")
    assert "2020 Hanna" in texts


def test_map_page_does_not_load_plotly(page, live_server):
    requested = []
    page.on("request", lambda request: requested.append(request.url))

    page.goto(f"{live_server}/?test=1")
    wait_js(page, "window.__rgvMap && window.__rgvMap.isStyleLoaded()")

    assert not [url for url in requested if "plotly" in url]
