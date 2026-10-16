"""Pages: the map explorer and the claims page, their shell and their policies."""

import base64
import hashlib
import re

from rgv_flood import pages


def test_map_page_renders(api_client):
    response = api_client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    html = response.text
    assert "<title>RGV Flood Impact Visualizer</title>" in html
    assert 'href="/claims"' in html and "Map explorer" in html
    assert 'data-theme="light"' in html  # the default before the bootstrap script runs
    assert "/static/vendor/alpine/alpine-csp.min.js" in html
    assert "Educational project only" not in html  # removed at the reader's request
    assert "A UTRGV Computer Science senior project" not in html


def test_claims_page_renders(api_client):
    response = api_client.get("/claims")

    assert response.status_code == 200
    assert "Claims &amp; rainfall by year" in response.text


def test_analysis_redirects(api_client):
    response = api_client.get("/analysis", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/claims"


def test_county_selector_lists_the_four_counties(api_client):
    html = api_client.get("/").text

    for slug in ("cameron", "hidalgo", "starr", "willacy"):
        assert f'value="{slug}"' in html


def test_no_inline_event_handlers(api_client):
    for path in ("/", "/claims"):
        assert not re.search(r"\son[a-z]+\s*=", api_client.get(path).text), path


def test_inline_script_hash_in_csp(api_client):
    response = api_client.get("/")
    digest = base64.b64encode(hashlib.sha256(pages.THEME_BOOTSTRAP.encode()).digest()).decode()

    assert pages.THEME_BOOTSTRAP in response.text
    assert f"'sha256-{digest}'" in response.headers["content-security-policy"]


def test_catalog_embedded_for_scripts(api_client):
    assert '<script type="application/json" id="i18n">' in api_client.get("/").text


def test_build_date_in_claims_footer(api_client):
    assert "Data built Oct 15, 2026" in api_client.get("/claims").text


def test_pages_render_before_build(make_client, tmp_path):
    client = make_client(tmp_path / "not-built.sqlite3")

    for path in ("/", "/claims"):
        response = client.get(path)
        assert response.status_code == 200
        assert "No data yet" in response.text


def test_favicon_is_the_wave_logo(api_client):
    html = api_client.get("/").text

    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg?v=' in html
    icon = api_client.get("/static/favicon.svg")
    assert icon.status_code == 200
    assert 'fill="#CB4900"' in icon.text


def test_no_logo_mark_in_the_header(api_client):
    header = api_client.get("/").text.split("<header", 1)[1].split("</header>", 1)[0]

    assert "bg-brand" not in header  # the old droplet mark
    assert "RGV Flood Impact Visualizer" in header


def test_map_page_loads_one_entry_module(api_client):
    """Modules imported by other modules must not also get their own (versioned) script
    tag: the browser would run them twice, e.g. registering two click handlers."""
    html = api_client.get("/").text

    modules = [line for line in html.splitlines() if 'type="module"' in line]
    assert len(modules) == 2  # store.js and the page entry
    assert "/static/js/pages/map.js?v=" in html
