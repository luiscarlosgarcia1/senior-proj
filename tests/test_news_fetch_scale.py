"""Pipeline: the fetcher at scale — threads, compressed cache, limits, crawl-delay, blocking and retries."""

import threading
import time
import urllib.error

from news_fetch import Fetcher


def http_error(url, code, headers=None):
    return urllib.error.HTTPError(url, code, "x", headers or {}, None)


class Web:
    """A scripted network: url -> bytes or an exception; counts calls and how many ran at once."""

    def __init__(self, pages, pause=0.0):
        self.pages, self.pause = pages, pause
        self.calls, self.active, self.most_at_once = [], 0, 0
        self._lock = threading.Lock()

    def __call__(self, url, limit=None):
        with self._lock:
            self.calls.append(url)
            self.active += 1
            self.most_at_once = max(self.most_at_once, self.active)
        try:
            if self.pause:
                time.sleep(self.pause)
            page = self.pages.get(url)
            if isinstance(page, list):  # a script: the next entry each time
                page = page.pop(0)
            if isinstance(page, Exception):
                raise page
            if page is None:
                raise http_error(url, 404)
            return page[:limit] if limit else page
        finally:
            with self._lock:
                self.active -= 1


def make(tmp_path, web, sleeps=None, **options):
    sleeps = [] if sleeps is None else sleeps
    return Fetcher(tmp_path / "cache", delay=0.0, get=web, sleep=sleeps.append, clock=lambda: 100.0, **options), sleeps


def test_new_downloads_are_stored_compressed_and_read_back(tmp_path):
    web = Web({"https://a.test/1": b"<html>" + b"x" * 5000})
    fetcher, _ = make(tmp_path, web)
    body = fetcher.get("https://a.test/1")

    (stored,) = [p for p in (tmp_path / "cache" / "a.test").iterdir()]
    assert stored.read_bytes()[:2] == b"\x1f\x8b" and stored.stat().st_size < len(body)
    again, _ = make(tmp_path, web)
    assert again.get("https://a.test/1") == body and again.stats["cached"] == 1


def test_a_cache_file_from_before_compression_is_still_read(tmp_path):
    first, _ = make(tmp_path, Web({"https://a.test/1": b"old page"}))
    first.get("https://a.test/1")
    (stored,) = (tmp_path / "cache" / "a.test").iterdir()
    stored.write_bytes(b"plain old cached page")  # what the earlier builds left behind

    again, _ = make(tmp_path, Web({}))

    assert again.get("https://a.test/1") == b"plain old cached page"


def test_a_byte_limit_is_applied_and_cached(tmp_path):
    web = Web({"https://a.test/long": b"0123456789" * 100})
    fetcher, _ = make(tmp_path, web)

    assert fetcher.get("https://a.test/long", limit=50) == b"0123456789" * 5
    assert fetcher.get("https://a.test/long") == b"0123456789" * 5  # what is cached is what was kept


def test_a_hosts_crawl_delay_is_honored(tmp_path):
    web = Web({"https://a.test/robots.txt": b"User-agent: *\nCrawl-delay: 7\n", "https://a.test/1": b"1", "https://a.test/2": b"2"})
    fetcher, sleeps = make(tmp_path, web)

    fetcher.get("https://a.test/1")
    fetcher.get("https://a.test/2")

    assert sleeps and all(s == 7 for s in sleeps)


def test_an_unreasonably_long_crawl_delay_skips_the_host(tmp_path):
    web = Web({"https://slow.test/robots.txt": b"User-agent: *\nCrawl-delay: 300\n", "https://slow.test/1": b"1"})
    fetcher, _ = make(tmp_path, web)

    assert fetcher.get("https://slow.test/1") is None
    assert "https://slow.test/1" not in web.calls and fetcher.stats["crawl_delay_too_long"] == 1


def test_one_request_at_a_time_per_host_but_hosts_run_side_by_side(tmp_path):
    same = Web({f"https://a.test/{n}": b"x" for n in range(8)} | {"https://a.test/robots.txt": b""}, pause=0.02)
    fetcher, _ = make(tmp_path, same)
    run(lambda n: fetcher.get(f"https://a.test/{n}"), range(8))
    assert same.most_at_once == 1

    pages = {f"https://h{n}.test/1": b"x" for n in range(4)} | {f"https://h{n}.test/robots.txt": b"" for n in range(4)}
    apart = Web(pages, pause=0.05)
    fetcher, _ = make(tmp_path / "b", apart)
    run(lambda n: fetcher.get(f"https://h{n}.test/1"), range(4))
    assert apart.most_at_once > 1


def run(work, items):
    threads = [threading.Thread(target=work, args=(item,)) for item in items]
    [t.start() for t in threads]
    [t.join() for t in threads]


def test_a_host_that_keeps_refusing_is_left_alone(tmp_path):
    refused = {f"https://nope.test/{n}": http_error(f"https://nope.test/{n}", 403) for n in range(12)}
    web = Web(refused | {"https://nope.test/robots.txt": b""})
    fetcher, _ = make(tmp_path, web)

    results = [fetcher.get(f"https://nope.test/{n}") for n in range(12)]

    assert results == [None] * 12
    assert len([c for c in web.calls if not c.endswith("robots.txt")]) == Fetcher.BLOCK_AFTER
    assert fetcher.stats["host_blocked"] == 12 - Fetcher.BLOCK_AFTER and "nope.test" in fetcher.blocked_hosts


def test_one_success_resets_the_refusal_count(tmp_path):
    pages = {"https://mixed.test/robots.txt": b"", "https://mixed.test/ok": b"fine"}
    pages |= {f"https://mixed.test/{n}": http_error(f"https://mixed.test/{n}", 403) for n in range(4)}
    fetcher, _ = make(tmp_path, Web(pages))
    for n in range(4):
        fetcher.get(f"https://mixed.test/{n}")

    fetcher.get("https://mixed.test/ok")  # four refusals, then a success: the count starts again
    for n in range(4):
        fetcher.get(f"https://mixed.test/{n}")  # four more refusals: eight in all, but never five in a row

    assert "mixed.test" not in fetcher.blocked_hosts


def test_a_429_is_retried_once_after_the_wait_it_asks_for(tmp_path):
    url = "https://busy.test/1"
    web = Web({"https://busy.test/robots.txt": b"", url: [http_error(url, 429, {"Retry-After": "3"}), b"finally"]})
    fetcher, sleeps = make(tmp_path, web)

    assert fetcher.get(url) == b"finally"
    assert 3 in sleeps


def test_a_second_429_is_a_failure_not_a_loop(tmp_path):
    url = "https://busy.test/2"
    web = Web({"https://busy.test/robots.txt": b"", url: [http_error(url, 429), http_error(url, 429), b"never"]})
    fetcher, _ = make(tmp_path, web)

    assert fetcher.get(url) is None and fetcher.stats["failed"] == 1


def test_stats_stay_exact_across_threads(tmp_path):
    pages = {f"https://t.test/{n}": b"x" for n in range(40)} | {"https://t.test/robots.txt": b""}
    fetcher, _ = make(tmp_path, Web(pages))

    run(lambda n: fetcher.get(f"https://t.test/{n}"), range(40))

    assert fetcher.stats["fetched"] == 40
