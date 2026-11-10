"""Water in the news: a source-first archive of publisher coverage."""

import re

from browser_support import wait_js
from playwright.sync_api import expect


def _open(page, live_server):
    page.goto(f"{live_server}/news")
    wait_js(page, "document.querySelectorAll('[data-outlet]').length > 0")
    return page


def test_news_page_groups_the_archive_by_publisher(page, live_server, console_errors):
    _open(page, live_server)

    expect(page.locator("[data-outlet-directory] [data-outlet]")).to_have_count(1)
    expect(page.locator("[data-outlet-archive]")).to_contain_text("KRGV Channel 5 News")
    expect(page.locator("[data-source-stories] a")).to_have_count(3)
    expect(page.locator("[data-coverage-context]")).to_contain_text("3")
    assert console_errors == []


def test_topic_filter_narrows_the_selected_publishers_archive(page, live_server):
    _open(page, live_server)

    topic = page.get_by_role("button", name="Rain")
    topic.click()

    expect(topic).to_have_class(re.compile(r".*\bbg-brand\b.*"))
    expect(page.locator("[data-source-stories] a")).to_have_count(1)
    expect(page.locator("[data-source-stories]")).to_contain_text("Hidalgo County drainage crews")


def test_the_county_narrows_the_page(page, live_server):
    _open(page, live_server)

    page.locator("#county-news").select_option("cameron")

    expect(page.locator("[data-coverage-context]")).to_contain_text("1")


def test_every_page_links_to_the_news_page(page, live_server):
    page.goto(f"{live_server}/trends")

    page.locator("header a[href='/news']").click()

    expect(page).to_have_url(f"{live_server}/news")
