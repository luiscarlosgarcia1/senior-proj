"""Pipeline: pipeline/news_fetch.py — robots.txt, pacing and the on-disk cache."""

import urllib.error

import pytest
from news_fetch import Fetcher, normalize_url


class FakeWeb:
    """Stands in for net.get_bytes: serves a dict of url -> bytes, or raises."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        if page is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return page


@pytest.fixture()
def sleeps():
    return []


def make(tmp_path, web, sleeps):
    return Fetcher(tmp_path / "cache", delay=1.0, get=web, sleep=sleeps.append, clock=lambda: 100.0)


def test_disallowed_path_is_never_requested(tmp_path, sleeps):
    web = FakeWeb({"https://a.test/robots.txt": b"User-agent: *\nDisallow: /private/\n"})
    fetcher = make(tmp_path, web, sleeps)

    assert fetcher.get("https://a.test/private/x") is None

    assert "https://a.test/private/x" not in web.calls
    assert fetcher.stats["blocked_by_robots"] == 1


def test_robots_404_means_no_rules(tmp_path, sleeps):
    web = FakeWeb({"https://a.test/news/1": b"<html>1</html>"})  # robots.txt is a 404
    fetcher = make(tmp_path, web, sleeps)

    assert fetcher.get("https://a.test/news/1") == b"<html>1</html>"


def test_robots_network_error_skips_the_host(tmp_path, sleeps):
    web = FakeWeb({"https://a.test/robots.txt": OSError("down"), "https://a.test/news/1": b"x"})
    fetcher = make(tmp_path, web, sleeps)

    assert fetcher.get("https://a.test/news/1") is None
    assert "https://a.test/news/1" not in web.calls


def test_second_request_to_a_host_waits_the_delay(tmp_path, sleeps):
    web = FakeWeb({"https://a.test/robots.txt": b"", "https://a.test/1": b"1", "https://a.test/2": b"2"})
    fetcher = make(tmp_path, web, sleeps)

    fetcher.get("https://a.test/1")
    fetcher.get("https://a.test/2")

    assert sleeps == [1.0, 1.0]  # robots.txt went first, undelayed; then each page waited


def test_other_hosts_are_not_delayed_by_the_first(tmp_path, sleeps):
    web = FakeWeb({
        "https://a.test/robots.txt": b"", "https://a.test/1": b"1",
        "https://b.test/robots.txt": b"User-agent: *\nDisallow: /\n",
    })
    fetcher = make(tmp_path, web, sleeps)

    fetcher.get("https://a.test/1")
    before = list(sleeps)
    fetcher.get("https://b.test/anything")

    assert sleeps == before


def test_cached_response_is_not_refetched_or_delayed(tmp_path, sleeps):
    web = FakeWeb({"https://a.test/robots.txt": b"", "https://a.test/1": b"1"})
    first = make(tmp_path, web, sleeps)
    first.get("https://a.test/1")
    calls, slept = len(web.calls), len(sleeps)

    again = make(tmp_path, web, sleeps)  # a new run, same cache folder

    assert again.get("https://a.test/1") == b"1"
    assert len(web.calls) == calls and len(sleeps) == slept
    assert again.stats["cached"] == 1


def test_http_error_counts_as_failed_and_is_not_cached(tmp_path, sleeps):
    web = FakeWeb({"https://a.test/robots.txt": b"", "https://a.test/1": urllib.error.HTTPError("u", 500, "x", {}, None)})
    fetcher = make(tmp_path, web, sleeps)

    assert fetcher.get("https://a.test/1") is None
    assert fetcher.stats["failed"] == 1
    web.pages["https://a.test/1"] = b"ok now"
    assert fetcher.get("https://a.test/1") == b"ok now"


def test_normalize_url():
    assert normalize_url("http://WWW.KRGV.com/news/a?utm_source=x&id=7#top") == "https://www.krgv.com/news/a?id=7"
    assert normalize_url("https://www.krgv.com/news/a?fbclid=abc") == "https://www.krgv.com/news/a"
