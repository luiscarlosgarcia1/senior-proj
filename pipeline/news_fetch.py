"""A polite fetcher for news sites: obeys robots.txt, waits between requests to a
host, and keeps every page it downloads in the download cache.

A page already in the cache is returned without any network request, so a
rebuild only fetches what is missing and works offline once the cache is full.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import net
from net import NETWORK_ERRORS
from paths import DOWNLOAD_CACHE

NEWS_CACHE = DOWNLOAD_CACHE / "news"
TRACKING_PARAMS = frozenset(("fbclid", "gclid"))


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
    def __init__(
        self,
        cache_dir: Path = NEWS_CACHE,
        *,
        delay: float = 1.0,
        get: Callable[[str], bytes] = net.get_bytes,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay = delay
        self._get, self._sleep, self._clock = get, sleep, clock
        self._robots: dict[str, RobotFileParser | None] = {}  # None: the host could not be checked, so skip it
        self._last_request: dict[str, float] = {}
        self.stats: Counter[str] = Counter()

    # ---- network, paced

    def _request(self, url: str) -> bytes:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.delay - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        try:
            return self._get(url)
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
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        parser = self._robots_for(url)
        return parser is not None and parser.can_fetch(net.USER_AGENT["User-Agent"], url)

    # ---- the cache

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / urlsplit(url).netloc / hashlib.sha1(url.encode()).hexdigest()

    def get(self, url: str) -> bytes | None:
        """The page's bytes, or None if robots.txt forbids it or it can't be fetched."""
        url = normalize_url(url)
        cached = self._cache_path(url)
        if cached.is_file() and cached.stat().st_size > 0:
            self.stats["cached"] += 1
            return cached.read_bytes()
        if not self.allowed(url):
            self.stats["blocked_by_robots"] += 1
            return None
        try:
            body = self._request(url)
        except NETWORK_ERRORS:
            self.stats["failed"] += 1
            return None
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(body)
        self.stats["fetched"] += 1
        return body
