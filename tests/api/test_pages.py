"""Pages: the landing page, the map explorer and the claims page, their shell and their policies."""

import base64
import hashlib
import re

from rgv_flood import pages


def test_landing_page_is_the_front_door(api_client):
    response = api_client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    html = response.text
    assert 'href="/map"' in html and 'href="/claims"' in html
    for county in ("Cameron", "Hidalgo", "Starr", "Willacy"):
        assert county in html
    assert 'href="https://www.weather.gov/bro/"' in html  # where to go in a real flood
    assert "maplibre" not in html  # the heavy map code belongs to /map
    assert "/static/js/pages/landing.js?v=" in html
    assert len([line for line in html.splitlines() if 'type="module"' in line]) == 2  # store.js and the page entry


def test_landing_page_needs_no_database(make_client, tmp_path):
    response = make_client(tmp_path / "not-built.sqlite3").get("/")

    assert response.status_code == 200
    assert 'role="status"' not in response.text  # no "No data yet" banner: it is shown before there is any data
    assert 'href="/map"' in response.text


def test_map_page_renders(api_client):
    response = api_client.get("/map")

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


def test_county_selector_lists_the_four_counties(api_client):
    html = api_client.get("/map").text

    for slug in ("cameron", "hidalgo", "starr", "willacy"):
        assert f'value="{slug}"' in html


def test_no_inline_event_handlers(api_client):
    for path in ("/", "/map", "/claims"):
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

    for path in ("/map", "/claims"):
        response = client.get(path)
        assert response.status_code == 200
        assert "No data yet" in response.text


def test_favicon_is_the_wave_logo(api_client):
    html = api_client.get("/map").text

    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg?v=' in html
    icon = api_client.get("/static/favicon.svg")
    assert icon.status_code == 200
    assert 'fill="#CB4900"' in icon.text


def test_no_logo_mark_in_the_header(api_client):
    header = api_client.get("/map").text.split("<header", 1)[1].split("</header>", 1)[0]

    assert "bg-brand" not in header  # the old droplet mark
    assert "RGV Flood Impact Visualizer" in header
    assert '<a href="/" class="flex items-center no-underline' in header  # the title leads back to the landing page
    assert 'href="/map"' in header and 'aria-current="page"' in header


def test_map_page_loads_one_entry_module(api_client):
    """Modules imported by other modules must not also get their own (versioned) script
    tag: the browser would run them twice, e.g. registering two click handlers."""
    html = api_client.get("/map").text

    modules = [line for line in html.splitlines() if 'type="module"' in line]
    assert len(modules) == 2  # store.js and the page entry
    assert "/static/js/pages/map.js?v=" in html


def test_claims_table_says_where_each_column_comes_from(api_client):
    html = api_client.get("/claims").text
    notes = html[html.index("data-column-notes"):]

    for column in ("Claims, Paid", "Per 1,000 pol.", "Rain, in · Wettest day, in", "Event"):
        assert f">{column}</dt>" in notes
    links = re.findall(r'href="([^"]+)"', notes[: notes.index("</dl>")])
    assert links == [
        "https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3",
        "https://www.fema.gov/openfema-data-page/nfip-redacted-policies-v3",
        "https://www.ncei.noaa.gov/cdo-web/search?datasetid=GHCND",
        "https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3",
    ]
    assert "/api/open/" not in html  # pages people can read, not the raw API


def test_trends_page_renders(api_client):
    response = api_client.get("/trends")

    assert response.status_code == 200
    assert 'id="trends-page"' in response.text
    assert 'href="/trends"' in api_client.get("/").text  # the header links to it
    assert response.headers["cache-control"] == "no-cache"
    assert not re.search(r"\son[a-z]+\s*=", response.text)


def test_trends_page_renders_before_build(make_client, tmp_path):
    response = make_client(tmp_path / "not-built.sqlite3").get("/trends")

    assert response.status_code == 200 and "No data yet" in response.text


def test_news_page_renders_and_every_page_links_to_it(api_client):
    response = api_client.get("/news")

    assert response.status_code == 200
    assert 'id="news-page"' in response.text and "js/pages/news.js" in response.text
    for section in ("data-outlet-directory", "data-outlet-archive", "data-source-stories", "data-coverage-context"):
        assert section in response.text, section
    assert 'href="/news"' in api_client.get("/").text and 'href="/news"' in api_client.get("/map").text
    assert response.headers["cache-control"] == "no-cache"
    assert not re.search(r"\son[a-z]+\s*=", response.text)


def test_news_page_renders_before_build(make_client, tmp_path):
    response = make_client(tmp_path / "not-built.sqlite3").get("/news")

    assert response.status_code == 200 and "No data yet" in response.text


def test_a_story_says_when_its_headline_was_rebuilt_from_the_web_address_and_who_else_told_it(api_client):
    html = api_client.get("/map").text

    assert "data-from-address" in html and "data-also-reported" in html  # in the news panel and an event's news


# ---- the chat box ----

PAGES = ("/", "/map", "/claims", "/trends", "/news")


def test_chat_button_is_absent_when_chat_is_off(api_client):
    for path in PAGES:
        assert "data-chat" not in api_client.get(path).text, path


def test_chat_button_is_on_every_page_when_chat_is_on(make_client, fixture_db, tmp_path):
    client = make_client(
        fixture_db, chat_usage_database=tmp_path / "usage.sqlite3", azure_openai_endpoint="https://az.invalid",
        azure_openai_api_key="not-a-real-key", azure_openai_deployment="none", session_secret="x" * 40,
    )

    for path in PAGES:
        html = client.get(path).text
        assert "data-chat-toggle" in html and "data-chat-panel" in html, path
        assert "not-a-real-key" not in html and "x" * 40 not in html  # no secret reaches a page
