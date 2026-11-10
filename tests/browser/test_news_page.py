"""Water in the news: news against the measurements, the busiest days and their timelines, places, water-service
problems and coverage by county."""

from browser_support import wait_js
from playwright.sync_api import expect


def _open(page, live_server):
    page.goto(f"{live_server}/news")
    wait_js(page, "document.querySelectorAll('[data-chart].js-plotly-plot').length === 2")
    return page


def test_news_page_draws_both_charts_and_every_section(page, live_server, console_errors):
    _open(page, live_server)

    stories = page.evaluate("document.querySelector('[data-chart=stories]').data[0].y.reduce((a, b) => a + b, 0)")
    assert stories == 3  # the fixture's three stories are all flood, rain or storm stories
    expect(page.locator("[data-tile=stories] [data-value]")).to_have_text("3")
    for section in ("[data-busiest]", "[data-places]", "[data-water-systems]", "[data-coverage]"):
        expect(page.locator(section)).to_be_visible()
    expect(page.locator("[data-coverage] tbody tr")).to_have_count(4)
    assert console_errors == []


def test_a_busy_day_opens_every_outlets_stories_day_by_day(page, live_server):
    _open(page, live_server)
    day = page.locator("[data-day]").first
    expect(day).to_contain_text("Jul 27, 2020")

    day.click()

    timeline = page.locator("[data-timeline]")
    expect(timeline).to_be_visible()
    expect(timeline.locator("[data-timeline-story]")).to_have_count(2)
    expect(timeline).to_contain_text("Flooding closes Weslaco streets")
    expect(day).to_have_attribute("aria-pressed", "true")


def test_the_county_narrows_the_page(page, live_server):
    _open(page, live_server)

    page.locator("#county-news").select_option("cameron")

    expect(page.locator("[data-tile=stories] [data-value]")).to_have_text("1")


def test_every_page_links_to_the_news_page(page, live_server):
    page.goto(f"{live_server}/trends")

    page.locator("header a[href='/news']").click()

    expect(page).to_have_url(f"{live_server}/news")
