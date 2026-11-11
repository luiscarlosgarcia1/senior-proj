"""The landing page: the first thing a visitor sees, before any map or data."""

from playwright.sync_api import expect


def test_landing_page_names_the_project_and_opens_the_map(page, live_server, console_errors):
    page.goto(f"{live_server}/")

    expect(page.locator("h1")).to_contain_text("Rio Grande Valley")
    page.get_by_role("link", name="Open the map").first.click()

    page.wait_for_url("**/map")
    assert console_errors == []


def test_landing_page_links_to_claims_and_lists_the_counties(page, live_server):
    page.goto(f"{live_server}/")

    expect(page.locator("[data-county]")).to_have_text(["Cameron", "Hidalgo", "Starr", "Willacy"])
    expect(page.locator("#landing").get_by_role("link", name="Claims & Rainfall by Year")).to_have_attribute("href", "/claims")


def test_old_shared_map_links_still_open_the_map(page, live_server):
    """Before the landing page, a shared link was the front page plus a #hash."""
    page.goto(f"{live_server}/#county=hidalgo&layers=fema-nfhl")

    page.wait_for_url("**/map#county=hidalgo&layers=fema-nfhl")


def test_landing_page_fits_a_phone(page, live_server):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_server}/")

    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    expect(page.get_by_role("link", name="Open the map").first).to_be_visible()


def test_landing_page_follows_the_dark_theme(page, live_server):
    page.goto(f"{live_server}/")
    light = page.evaluate("getComputedStyle(document.body).backgroundColor")

    page.locator("header label:has-text('Dark') input").check()

    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != light
