"""Map popups: one per kind of feature, the FEMA gallery, the selection ring."""

from browser_support import click_lnglat, wait_js
from playwright.sync_api import expect

RAYMONDVILLE = (-97.78, 26.48)  # the FEMA town in the browser fixture


def _turn_on(page, row):
    page.locator(f'[data-row="{row}"] > label:not([data-sub]) input[type=checkbox]').check()
    wait_js(page, f"window.__rgvMap.getSource('src-{row}') && window.__rgvMap.isSourceLoaded('src-{row}')")
    page.wait_for_timeout(250)  # let the first frame draw


def test_fema_gallery_pages(map_page):
    page = map_page()
    _turn_on(page, "fema-flood-photos")

    click_lnglat(page, *RAYMONDVILLE)

    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("Raymondville")
    expect(popup).to_contain_text("5 FEMA photos of flooding")
    expect(popup.locator("[data-counter]")).to_have_text("1 / 5")
    expect(popup.locator("[data-caption]")).to_contain_text("number 1")
    popup.locator("[data-step='1']").click()
    expect(popup.locator("[data-counter]")).to_have_text("2 / 5")
    expect(popup.locator("[data-caption]")).to_contain_text("number 2")
    popup.locator("[data-step='-1']").click()
    popup.locator("[data-step='-1']").click()
    expect(popup.locator("[data-counter]")).to_have_text("5 / 5")  # wraps around
    popup.locator("[data-thumb]").nth(2).click()
    expect(popup.locator("[data-counter]")).to_have_text("3 / 5")
    expect(popup).to_contain_text("Placed at the town FEMA's caption names")


def test_photo_popup_shows_image(map_page):
    page = map_page()
    _turn_on(page, "hcdd1-flood-photos")

    click_lnglat(page, -98.2, 26.2)

    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("Flood photo")
    expect(popup.locator("img")).to_have_count(1)


def test_location_only_popup_says_not_published(map_page):
    page = map_page()
    _turn_on(page, "hcdd1-flood-photos")

    click_lnglat(page, -98.1, 26.3)

    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("Photo location")
    expect(popup).to_contain_text("has not published the image")
    expect(popup.locator("img")).to_have_count(0)


def test_infrastructure_popup_source_line(map_page):
    page = map_page()
    _turn_on(page, "flood-infrastructure")

    click_lnglat(page, -98.4, 26.1)

    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("Retamal Diversion Dam")
    expect(popup).to_contain_text("Source: Overture Maps Foundation (OpenStreetMap)")


def test_popup_text_is_escaped(map_page):
    page = map_page()
    _turn_on(page, "flood-infrastructure")

    click_lnglat(page, -98.0, 26.45)

    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("<b>x</b>")
    expect(popup.locator("b")).to_have_count(0)


def test_selection_ring_on_click(map_page):
    page = map_page()
    _turn_on(page, "flood-infrastructure")

    click_lnglat(page, -98.4, 26.1)

    wait_js(page, "window.__rgvMap.getLayer('lyr-selection') !== undefined")
    ring = page.evaluate("window.__rgvMap.getSource('selection').serialize().data.features[0].geometry.coordinates")
    assert [round(c, 2) for c in ring] == [-98.4, 26.1]


def test_hazard_zone_popup(map_page):
    page = map_page()
    _turn_on(page, "fema-nfhl")

    click_lnglat(page, -98.2, 26.2)

    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("FEMA NFHL")
    expect(popup).to_contain_text("Zone AE")
    expect(popup).to_contain_text("Relative severity: high")
