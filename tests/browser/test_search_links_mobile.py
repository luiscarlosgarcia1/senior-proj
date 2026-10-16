"""Map page: address search, shareable links, the phone layout."""

from urllib.parse import parse_qs

from browser_support import wait_js
from playwright.sync_api import expect

PLACES = [{"label": "1200 W University Dr, Edinburg, Texas", "lon": -98.1735, "lat": 26.3049}]


def _hash(page) -> dict:
    return {key: values[0] for key, values in parse_qs(page.evaluate("location.hash").lstrip("#")).items()}


def _row(page, row):
    return page.locator(f'[data-row="{row}"] > label:not([data-sub]) input[type=checkbox]')


def test_search_flies_to_result(map_page):
    page = map_page()
    page.route("**/api/v1/geocode?**", lambda route: route.fulfill(json=PLACES))

    page.locator("[data-search] input:visible").fill("1200 W University")
    page.locator("[data-search] [data-result]:visible").first.click()

    wait_js(page, "!window.__rgvMap.isMoving() && window.__rgvMap.getZoom() > 14")
    center = page.evaluate("window.__rgvMap.getCenter().toArray()")
    assert abs(center[0] - -98.1735) < 0.01 and abs(center[1] - 26.3049) < 0.01


def test_search_unavailable_message(map_page):
    page = map_page()
    page.route("**/api/v1/geocode?**", lambda route: route.fulfill(status=502, json={"detail": "Search is unavailable right now"}))

    page.locator("[data-search] input:visible").fill("Weslaco")

    expect(page.locator("[data-search]:visible")).to_contain_text("Search is unavailable right now")


def test_slash_focuses_search(map_page):
    page = map_page()

    page.locator("body").press("/")

    assert page.evaluate("document.activeElement.closest('[data-search]') !== null")


def test_share_link_round_trip(map_page, browser):
    page = map_page()
    page.locator("#county-header").select_option("hidalgo")
    _row(page, "fema-nfhl").check()
    _row(page, "hcdd1-flood-photos").check()
    page.locator('[data-row="hcdd1-flood-photos"] [data-sub="locations"] input').uncheck()
    page.locator("[data-event='noaa-storm-events-1']").click()
    wait_js(page, "location.hash.includes('event=')")
    page.wait_for_timeout(1200)  # let the map settle so its view is in the link
    link = page.evaluate("location.href")

    other = browser.new_page()
    other.goto(link)
    wait_js(other, "window.__rgvMap && window.__rgvMap.getLayer('lyr-fema-nfhl-fill') !== undefined")

    expect(_row(other, "fema-nfhl")).to_be_checked()
    expect(_row(other, "hcdd1-flood-photos")).to_be_checked()
    expect(other.locator('[data-row="hcdd1-flood-photos"] [data-sub="locations"] input')).not_to_be_checked()
    expect(other.locator("#county-header")).to_have_value("hidalgo")
    expect(other.locator("[data-event-detail]")).to_contain_text("Flash flood")
    state = _hash(page)
    assert _hash(other)["map"] == state["map"]
    other.close()


def test_stale_share_link_is_ignored_gracefully(map_page, console_errors):
    page = map_page("#layers=overture-dams,unknown,fema-nfhl&off=x.y&map=nonsense&county=texas&event=nope")

    expect(_row(page, "fema-nfhl")).to_be_checked()
    expect(page.locator("#county-header")).to_have_value("")
    assert [e for e in console_errors if "404" not in e] == []


def test_old_flask_link_still_works(map_page):
    page = map_page("#county=hidalgo&layers=fema-nfhl&events=1&map=26.2034,-98.2300,11")

    expect(_row(page, "fema-nfhl")).to_be_checked()
    expect(_row(page, "noaa-flood-events")).to_be_checked()
    expect(page.locator("#county-header")).to_have_value("hidalgo")
    wait_js(page, "Math.abs(window.__rgvMap.getZoom() - 11) < 0.1")


def test_phone_layout_bottom_nav(page, live_server):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_server}/?test=1")
    wait_js(page, "window.__rgvMap && window.__rgvMap.isStyleLoaded()")
    nav = page.locator("nav[data-bottom-nav]")

    expect(nav).to_be_visible()
    expect(page.locator('aside[data-view="layers"]')).to_be_hidden()
    nav.locator("[data-view=layers]").click()
    expect(page.locator('aside[data-view="layers"]')).to_be_visible()
    expect(page.locator('main[data-view="map"]')).to_be_hidden()
    nav.locator("[data-view=map]").click()
    expect(page.locator('main[data-view="map"]')).to_be_visible()
    wait_js(page, "window.__rgvMap.getCanvas().clientWidth > 300")
    for button in nav.locator("button").all():
        assert button.bounding_box()["height"] >= 44
