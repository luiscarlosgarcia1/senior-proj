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


def test_hazard_layers_colored_by_severity(map_page):
    page = map_page()
    _row(page, "fema-nfhl").check()
    wait_js(page, LAYER.format("lyr-fema-nfhl-fill"))

    color = page.evaluate("window.__rgvMap.getPaintProperty('lyr-fema-nfhl-fill', 'fill-color')")
    tokens = page.evaluate("""(() => { const s = getComputedStyle(document.documentElement);
        return ['--sev-high', '--sev-mod', '--sev-low'].map(n => s.getPropertyValue(n).trim()); })()""")

    assert color[:2] == ["match", ["get", "relative_class"]]
    assert color[2:8] == ["high", tokens[0], "moderate", tokens[1], "low", tokens[2]]


def test_severity_colors_are_red_orange_blue(map_page):
    page = map_page()

    high, moderate, low = page.evaluate("""(() => { const s = getComputedStyle(document.documentElement);
        return ['--sev-high', '--sev-mod', '--sev-low'].map(n => s.getPropertyValue(n).trim()); })()""")

    def rgb(hex_):
        return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))

    r, g, b = rgb(high)
    assert r > 180 and g < 80 and b < 80  # red
    r, g, b = rgb(moderate)
    assert r > 200 and 100 < g < 180 and b < 60  # orange (amber, not the UTRGV brand orange)
    r, g, b = rgb(low)
    assert b > r and b > g  # blue
    expect(page.locator("[data-severity-legend] li")).to_have_text(["Severe", "Moderate", "Light", "Uncategorized"])


def test_dams_have_their_own_row(map_page):
    page = map_page()

    expect(page.locator('[data-group="works"] [data-row="dams"]')).to_contain_text("Dams")


def test_labels_in_mexico_are_hidden(map_page):
    page = map_page()

    result = page.evaluate("""(async () => {
      const labels = await import('/static/js/map/labels.js');
      const counties = {type: 'FeatureCollection', features: [{type: 'Feature', properties: {},
        geometry: {type: 'Polygon', coordinates: [[[-98.6, 26.0], [-97.2, 26.0], [-97.2, 26.6], [-98.6, 26.6], [-98.6, 26.0]]]}}]};
      const mask = labels.usSideMask(counties);
      const layers = labels.hideForeignLabels([
        {id: 'label_city', type: 'symbol', 'source-layer': 'place', filter: ['==', ['get', 'class'], 'city']},
        {id: 'highway', type: 'symbol', 'source-layer': 'transportation_name'},
        {id: 'water', type: 'symbol', 'source-layer': 'water_name'},
        {id: 'roads', type: 'line', 'source-layer': 'transportation'},
      ], mask);
      return {mask: mask.type, layers};
    })()""")

    city, highway, water, roads = result["layers"]
    assert result["mask"] == "MultiPolygon"
    assert city["filter"][0] == "all" and city["filter"][1] == ["==", ["get", "class"], "city"]
    assert city["filter"][2][0] == "within"
    assert highway["filter"][0] == "within"
    assert "filter" not in water  # the Rio Grande's name stays
    assert "filter" not in roads


def _tokens(page, *names):
    return page.evaluate(f"""(() => {{ const s = getComputedStyle(document.documentElement);
        return {list(names)!r}.map(n => s.getPropertyValue(n).trim()); }})()""")


def test_photos_you_can_open_and_photo_locations_have_different_colors(map_page):
    page = map_page()
    _row(page, "hcdd1-flood-photos").check()
    wait_js(page, LAYER.format("lyr-hcdd1-flood-photos-point"))

    color = page.evaluate("window.__rgvMap.getPaintProperty('lyr-hcdd1-flood-photos-point', 'circle-color')")
    photos, locations = _tokens(page, "--c-photos", "--c-photoloc")

    assert color == ["case", ["has", "photo_url"], photos, locations]
    assert photos and locations and photos != locations
    swatches = page.locator('[data-row="hcdd1-flood-photos"] [data-sub] i.sw')
    expect(swatches).to_have_count(2)
    assert swatches.evaluate_all("els => els.map(e => getComputedStyle(e).backgroundColor)") == [
        page.evaluate(f"(() => {{ const e = document.createElement('i'); e.style.color = {c!r}; document.body.append(e);"
                      " const v = getComputedStyle(e).color; e.remove(); return v; })()") for c in (photos, locations)
    ]


def test_twdb_one_percent_is_red_and_drawn_over_point_two_percent(map_page):
    page = map_page()
    _row(page, "twdb").check()
    wait_js(page, LAYER.format("lyr-twdb-cursory-1in100-fill") + " && " + LAYER.format("lyr-twdb-cursory-1in500-fill"))

    high, moderate = _tokens(page, "--sev-high", "--sev-mod")
    paint = "window.__rgvMap.getPaintProperty('lyr-twdb-cursory-{}-fill', 'fill-color')"
    assert page.evaluate(paint.format("1in100")) == high
    assert page.evaluate(paint.format("1in500")) == moderate
    expect(page.locator('[data-row="twdb"] [data-sub] i.sw')).to_have_count(2)

    # The 0.2% extent holds the whole 1% extent, so the 1% one goes on top to be seen,
    # and stays there when the theme switch rebuilds the style.
    order = "(() => { const o = window.__rgvMap.getLayersOrder();"             " return o.indexOf('lyr-twdb-cursory-1in100-fill') > o.indexOf('lyr-twdb-cursory-1in500-line'); })()"
    assert page.evaluate(order)
    page.locator("header label:has-text('Dark') input").check()
    wait_js(page, LAYER.format("lyr-twdb-cursory-1in100-fill") + " && " + LAYER.format("lyr-twdb-cursory-1in500-fill"))
    assert page.evaluate(order)
