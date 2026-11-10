"""A polite fetcher for news sites: obeys robots.txt and its crawl-delay, waits
between requests to a host, and keeps every page it downloads in the download cache.

Many hosts can be fetched side by side (one thread per publisher), but each host
sees one request at a time, at least `delay` seconds apart. A host that keeps
answering "forbidden" is left alone for the rest of the run: this crawler
identifies itself and never tries to look like a browser.

A page already in the cache is returned without any network request, so a
rebuild only fetches what is missing and works offline once the cache is full.
Cache files are gzip-compressed; files cached uncompressed by earlier builds are
still read.
"""

from __future__ import annotations

import gzip
import hashlib
import inspect
import threading
import time
import urllib.error
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import net
from net import NETWORK_ERRORS
from paths import DOWNLOAD_CACHE

NEWS_CACHE = DOWNLOAD_CACHE / "news"
TRACKING_PARAMS = frozenset(("fbclid", "gclid"))
GZIP_MAGIC = b"\x1f\x8b"
MAX_CRAWL_DELAY = 30.0  # a host asking for more than this between requests is skipped, not waited on
MAX_RETRY_WAIT = 120.0
MAX_PAUSE = 6 * 3600.0  # the longest we leave a host alone when it says "come back later"


def normalize_url(url: str) -> str:
    """The same story under one address: https, lower-case host, no tracking
    parameters, no fragment."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.startswith("utm_") and key not in TRACKING_PARAMS
    ]
    return urlunsplit(("https", parts.netloc.lower(), parts.path, urlencode(query), ""))


class Fetcher:
    BLOCK_AFTER = 5  # consecutive 401/403 answers before a host is left alone

    def __init__(
        self,
        cache_dir: Path = NEWS_CACHE,
        *,
        delay: float = 1.0,
        delays: Mapping[str, float] | None = None,
        get: Callable[..., bytes] = net.get_bytes,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay = delay
        self._get, self._sleep, self._clock = get, sleep, clock
        self._takes_limit = "limit" in inspect.signature(get).parameters
        self._robots: dict[str, RobotFileParser | None] = {}  # None: the host could not be checked, so skip it
        self._host_delay: dict[str, float] = dict(delays or {})  # hosts that must be asked less often than `delay`
        self._last_request: dict[str, float] = {}
        self._refusals: dict[str, int] = defaultdict(int)
        self._paused_until: dict[str, float] = {}  # hosts that told us to come back later
        self.blocked_hosts: set[str] = set()
        self._not_found: set[str] = set()
        self.stats: Counter[str] = Counter()
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}

    def _count(self, key: str) -> None:
        with self._lock:
            self.stats[key] += 1

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    # ---- network, paced (callers hold the host's lock)

    def _request(self, url: str, limit: int | None = None) -> bytes:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self._host_delay.get(host, self.delay) - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        try:
            return self._get(url, limit=limit) if self._takes_limit else self._get(url)
        finally:
            self._last_request[host] = self._clock()

    def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            parser = RobotFileParser()
            try:
                parser.parse(self._request(f"{parts.scheme}://{host}/robots.txt").decode("utf-8", errors="replace").splitlines())
            except urllib.error.HTTPError as error:
                # No robots.txt at all means no rules; any other answer, we can't tell.
                parser = parser if error.code in (404, 410) else None
                if parser is not None:
                    parser.parse([])
            except NETWORK_ERRORS:
                parser = None
            self._robots[host] = parser
            if parser is not None:
                asked = parser.crawl_delay(net.USER_AGENT["User-Agent"])
                if asked:
                    self._host_delay[host] = max(self.delay, float(asked), self._host_delay.get(host, 0.0))
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        with self._host_lock(urlsplit(url).netloc):
            parser = self._robots_for(url)
        return parser is not None and parser.can_fetch(net.USER_AGENT["User-Agent"], url)

    # ---- the cache

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / urlsplit(url).netloc / hashlib.sha1(url.encode()).hexdigest()

    @staticmethod
    def _read_cached(path: Path) -> bytes:
        data = path.read_bytes()
        return gzip.decompress(data) if data[:2] == GZIP_MAGIC else data

    # ---- the one public call

    def get(self, url: str, *, limit: int | None = None, use_cache: bool = True) -> bytes | None:
        """The page's bytes (only the first `limit` of them, if given), or None if robots.txt forbids
        it, the host is being left alone, it does not exist, or it can't be fetched. With `use_cache`
        False the page is always asked for and never stored (a page that changes, like today's sitemap)."""
        url = normalize_url(url)
        host = urlsplit(url).netloc
        cached = self._cache_path(url)
        missing = cached.with_suffix(".missing")
        if use_cache:
            if cached.is_file() and cached.stat().st_size > 0:
                self._count("cached")
                return self._read_cached(cached)
            if missing.exists():  # asked before and the publisher said it is not there
                self._count("known_missing")
                return None
        with self._host_lock(host):
            if host in self.blocked_hosts:
                self._count("host_blocked")
                return None
            if self._clock() < self._paused_until.get(host, 0.0):
                self._count("host_paused")
                return None
            parser = self._robots_for(url)
            if parser is None or not parser.can_fetch(net.USER_AGENT["User-Agent"], url):
                self._count("blocked_by_robots")
                return None
            if self._host_delay.get(host, 0) > MAX_CRAWL_DELAY:
                self._count("crawl_delay_too_long")
                return None
            body = self._download(url, host, limit)
        if body is None:
            if use_cache and url in self._not_found:
                self._not_found.discard(url)
                missing.parent.mkdir(parents=True, exist_ok=True)
                missing.touch()
            return None
        if use_cache:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(gzip.compress(body, 6))
        self._count("fetched")
        return body

    def _download(self, url: str, host: str, limit: int | None) -> bytes | None:
        for attempt in (1, 2):
            try:
                body = self._request(url, limit)
            except urllib.error.HTTPError as error:
                if error.code in (404, 410):
                    self._not_found.add(url)
                if error.code in (401, 403):
                    self._refusals[host] += 1
                    if self._refusals[host] >= self.BLOCK_AFTER:
                        self.blocked_hosts.add(host)
                elif error.code in (429, 503):
                    asked = self._retry_after(error)
                    if asked is not None and asked > MAX_RETRY_WAIT:
                        # "Come back in an hour": leave the host alone until then, not ask again in half a minute.
                        self._paused_until[host] = self._clock() + min(asked, MAX_PAUSE)
                    elif attempt == 1:
                        self._sleep(self._retry_wait(asked))
                        continue
                    else:
                        # Asked twice and told to slow down twice: ask less often for the rest of the run.
                        current = max(self._host_delay.get(host, self.delay), 1.0)
                        self._host_delay[host] = min(current * 2, MAX_CRAWL_DELAY)
                self._count("failed")
                return None
            except NETWORK_ERRORS:
                self._count("failed")
                return None
            self._refusals[host] = 0
            return body[:limit] if limit else body
        return None

    @staticmethod
    def _retry_after(error: urllib.error.HTTPError) -> float | None:
        """Seconds the server asked us to wait (its Retry-After header), or None if it gave no number."""
        try:
            return float((error.headers or {}).get("Retry-After", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _retry_wait(asked: float | None) -> float:
        return max(1.0, min(30.0 if asked is None else asked, MAX_RETRY_WAIT))

    def paused_hosts(self) -> dict[str, float]:
        """Hosts that asked us to come back later, and how many seconds of their wait are left."""
        now = self._clock()
        return {host: until - now for host, until in self._paused_until.items() if until > now}
