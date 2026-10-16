"""Map page: the MapLibre map, the layer panel, legends, source details, themes."""

from browser_support import wait_js
from playwright.sync_api import expect

LAYER = "window.__rgvMap.getLayer({!r}) !== undefined"


def _row(page, row):
    return page.locator(f'[data-row="{row}"] > label:not([data-sub]) input[type=checkbox]')


def test_map_loads_without_console_errors(map_page, console_errors):
    page = map_page()

    expect(page.locator('[data-group="hazard"]')).to_be_visible()
    assert console_errors == []


def test_group_checkbox_toggles_all_and_shows_indeterminate(map_page):
    page = map_page()
    group = page.locator('[data-group="hazard"] input[type=checkbox]').first

    group.check()
    expect(_row(page, "fema-nfhl")).to_be_checked()
    expect(_row(page, "twdb")).to_be_checked()

    _row(page, "fema-nfhl").uncheck()
    assert group.evaluate("el => el.indeterminate") is True
    expect(page.locator('[data-group="hazard"] [data-tally]')).to_have_text("1/2")


def test_sub_options_appear_only_when_parent_on(map_page):
    page = map_page()
    photos_parts = page.locator('[data-row="hcdd1-flood-photos"] [data-sub]')

    expect(photos_parts).to_have_count(0)
    _row(page, "hcdd1-flood-photos").check()
    expect(photos_parts).to_have_count(2)
    expect(photos_parts.first).to_contain_text("Photos you can open")


def test_layer_on_adds_maplibre_layer(map_page):
    page = map_page()

    _row(page, "fema-nfhl").check()

    wait_js(page, LAYER.format("lyr-fema-nfhl-fill"))
    _row(page, "fema-nfhl").uncheck()
    wait_js(page, "window.__rgvMap.getLayoutProperty('lyr-fema-nfhl-fill', 'visibility') === 'none'")


def test_tiled_layer_uses_vector_source(map_page):
    page = map_page()

    _row(page, "twdb").check()

    wait_js(page, "window.__rgvMap.getSource('src-twdb-cursory-1in100')?.type === 'vector'")
    wait_js(page, "window.__rgvMap.getSource('src-twdb-cursory-1in500')?.type === 'geojson'")


def test_sub_option_turns_one_layer_off(map_page):
    page = map_page()
    _row(page, "twdb").check()
    wait_js(page, LAYER.format("lyr-twdb-cursory-1in500-fill"))

    page.locator('[data-row="twdb"] [data-sub="twdb-cursory-1in500"] input').uncheck()

    wait_js(page, "window.__rgvMap.getLayoutProperty('lyr-twdb-cursory-1in500-fill', 'visibility') === 'none'")
    assert page.evaluate("window.__rgvMap.getLayoutProperty('lyr-twdb-cursory-1in100-fill', 'visibility')") == "visible"


def test_photo_part_filters(map_page):
    page = map_page()
    _row(page, "hcdd1-flood-photos").check()
    wait_js(page, LAYER.format("lyr-hcdd1-flood-photos-point"))

    page.locator('[data-row="hcdd1-flood-photos"] [data-sub="locations"] input').uncheck()

    wait_js(page, 
        "JSON.stringify(window.__rgvMap.getFilter('lyr-hcdd1-flood-photos-point')).includes('photo_url')"
    )


def test_legend_follows_active_layers(map_page):
    page = map_page()
    legend = page.locator("[data-legend] li")

    expect(legend).to_have_count(0)
    _row(page, "fema-nfhl").check()
    expect(legend).to_have_count(1)
    expect(legend.first).to_contain_text("FEMA effective flood hazard")


def test_source_details_open(map_page):
    page = map_page()

    page.locator('[data-info="fema-nfhl"]').click()

    details = page.locator("[data-source-details]")
    expect(details).to_be_visible()
    expect(details).to_contain_text("FEMA effective flood hazard (NFHL)")
    expect(details).to_contain_text("Somewhere")  # the fixture's source


def test_theme_switch_keeps_layers(map_page):
    page = map_page()
    _row(page, "fema-nfhl").check()
    wait_js(page, LAYER.format("lyr-fema-nfhl-fill"))
    dark = page.evaluate("window.__rgvMap.getPaintProperty('lyr-fema-nfhl-fill', 'fill-color')")

    page.locator("header label:has-text('Dark') input").check()

    wait_js(page, 
        f"window.__rgvMap.isStyleLoaded() && window.__rgvMap.getLayer('lyr-fema-nfhl-fill') && "
        f"JSON.stringify(window.__rgvMap.getPaintProperty('lyr-fema-nfhl-fill', 'fill-color')) !== {dark!r}"
    )
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"


def test_theme_switch_during_layer_load(map_page, console_errors):
    page = map_page()
    release = []
    page.route("**/api/v1/layers/fema-nfhl.geojson", lambda route: release.append(route))

    _row(page, "fema-nfhl").check()
    wait_js(page, "true")  # let the request start
    page.locator("header label:has-text('Dark') input").check()
    page.wait_for_timeout(300)
    for route in release:
        route.continue_()

    wait_js(page, LAYER.format("lyr-fema-nfhl-fill"))
    page.wait_for_timeout(300)
    sources = page.evaluate("Object.keys(window.__rgvMap.getStyle().sources).filter(id => id === 'src-fema-nfhl')")
    assert sources == ["src-fema-nfhl"]
    assert console_errors == []


def test_map_fills_its_area(map_page):
    page = map_page()

    box = page.locator("#map").bounding_box()
    main = page.locator('main[data-view="map"]').bounding_box()

    assert box["height"] > 300
    assert abs(box["height"] - main["height"]) < 2
    assert page.evaluate("window.__rgvMap.getCanvas().clientHeight") == round(box["height"])


def test_tiled_layer_draws_features(map_page, console_errors):
    page = map_page()

    _row(page, "twdb").check()

    wait_js(page, "window.__rgvMap.querySourceFeatures('src-twdb-cursory-1in100', "
                  "{sourceLayer: 'twdb-cursory-1in100'}).length > 0", timeout=15)
    assert console_errors == []


def test_opens_in_light_mode_even_when_the_system_is_dark(page, live_server):
    page.emulate_media(color_scheme="dark")
    page.goto(f"{live_server}/?test=1")

    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    expect(page.locator("header label:has-text('Dark') input")).not_to_be_checked()


def test_dark_choice_is_remembered(map_page, browser):
    page = map_page()
    page.locator("header label:has-text('Dark') input").check()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"

    page.reload()

    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    expect(page.locator("header label:has-text('Dark') input")).to_be_checked()
