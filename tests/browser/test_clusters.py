"""Dense point layers collapse into one dot when zoomed out and spread when zoomed in."""

from browser_support import click_lnglat, wait_js
from playwright.sync_api import expect

CENTER = (-98.2, 26.2)
PIXEL = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
LAYER = "lyr-hcdd1-flood-photos"


def photo_points(count=60):
    """`count` photo points within a few hundred metres: half open, half locations only."""
    features = []
    for n in range(count):
        properties = {"overlay_type": "flood_photo", "event": "June 2019", "taken": "2019-06-27 09:54"}
        if n % 2 == 0:
            properties["photo_url"] = PIXEL
        features.append({
            "type": "Feature", "properties": properties,
            "geometry": {"type": "Point", "coordinates": [CENTER[0] + (n % 10) * 0.0004, CENTER[1] + (n // 10) * 0.0004]},
        })
    return {"type": "FeatureCollection", "features": features}


def open_with_many_photos(page, map_page, zoom, center=None):
    page.route("**/api/v1/layers/hcdd1-flood-photos.geojson", lambda route: route.fulfill(json=photo_points()))
    map_page()
    page.locator('[data-row="hcdd1-flood-photos"] > label:not([data-sub]) input[type=checkbox]').check()
    wait_js(page, "window.__rgvMap.getSource('src-hcdd1-flood-photos') && window.__rgvMap.isSourceLoaded('src-hcdd1-flood-photos')")
    go_to(page, zoom, center)


def go_to(page, zoom, center=None):
    lng, lat = center or (CENTER[0] + 0.002, CENTER[1] + 0.001)  # by default, the middle of the 60 dots
    page.evaluate(f"window.__rgvMap.jumpTo({{center: [{lng}, {lat}], zoom: {zoom}}})")
    wait_js(page, "window.__rgvMap.areTilesLoaded()")
    page.wait_for_timeout(300)


def rendered(page, suffix):
    return page.evaluate(f"window.__rgvMap.queryRenderedFeatures({{layers: ['{LAYER}-{suffix}']}}).map(f => f.properties)")


def test_zoomed_out_photos_are_one_cluster_and_zoomed_in_they_spread(page, map_page):
    open_with_many_photos(page, map_page, zoom=8)

    clusters = rendered(page, "cluster")
    assert clusters and max(c["point_count"] for c in clusters) == 60
    assert rendered(page, "point") == []

    go_to(page, 16)

    assert rendered(page, "cluster") == []
    assert len(rendered(page, "point")) >= 60


def test_layers_with_few_points_do_not_cluster(map_page):
    page = map_page()
    page.locator('[data-row="hcdd1-flood-photos"] > label:not([data-sub]) input[type=checkbox]').check()
    wait_js(page, "window.__rgvMap.getLayer('lyr-hcdd1-flood-photos-point')")

    assert page.evaluate("window.__rgvMap.getLayer('lyr-hcdd1-flood-photos-cluster')") is None
    assert page.evaluate("window.__rgvMap.getSource('src-hcdd1-flood-photos').serialize().cluster") in (None, False)


def test_clicking_a_cluster_zooms_in_and_opens_no_popup(page, map_page):
    open_with_many_photos(page, map_page, zoom=8)
    cluster = page.evaluate(f"window.__rgvMap.queryRenderedFeatures({{layers: ['{LAYER}-cluster']}})[0].geometry.coordinates")

    click_lnglat(page, *cluster)

    wait_js(page, "window.__rgvMap.getZoom() > 9")
    expect(page.locator(".maplibregl-popup")).to_have_count(0)


def test_clicking_a_single_photo_still_opens_its_popup(page, map_page):
    open_with_many_photos(page, map_page, zoom=17, center=CENTER)  # centred on the first photo

    click_lnglat(page, CENTER[0], CENTER[1])

    expect(page.locator(".maplibregl-popup-content")).to_contain_text("Flood photo")


def test_cluster_follows_the_photo_sub_options(page, map_page):
    open_with_many_photos(page, map_page, zoom=8)
    sub = lambda name: page.locator(f'[data-row="hcdd1-flood-photos"] [data-sub="{name}"] input')

    sub("locations").uncheck()  # only the 30 photos you can open are left
    page.wait_for_timeout(300)
    assert rendered(page, "cluster"), "the cluster should stay while some photos are on"

    sub("photos").uncheck()  # nothing left to count
    page.wait_for_timeout(300)
    assert rendered(page, "cluster") == []
    assert rendered(page, "point") == []

    sub("photos").check()
    page.wait_for_timeout(300)
    assert rendered(page, "cluster")


def test_theme_switch_keeps_clusters(page, map_page, console_errors):
    open_with_many_photos(page, map_page, zoom=8)

    page.locator("header label:has-text('Dark') input").check()
    wait_js(page, "window.__rgvMap.isStyleLoaded()")
    page.wait_for_timeout(500)

    assert rendered(page, "cluster")
    assert console_errors == []


def test_turning_every_part_off_hides_the_dots_of_a_small_layer(map_page):
    page = map_page()
    page.locator('[data-row="hcdd1-flood-photos"] > label:not([data-sub]) input[type=checkbox]').check()
    wait_js(page, "window.__rgvMap.getLayer('lyr-hcdd1-flood-photos-point')")
    page.evaluate("window.__rgvMap.jumpTo({center: [-98.15, 26.25], zoom: 9})")
    wait_js(page, "window.__rgvMap.areTilesLoaded()")
    assert len(rendered(page, "point")) == 2

    for name in ("photos", "locations"):
        page.locator(f'[data-row="hcdd1-flood-photos"] [data-sub="{name}"] input').uncheck()
    page.wait_for_timeout(300)

    assert rendered(page, "point") == []
