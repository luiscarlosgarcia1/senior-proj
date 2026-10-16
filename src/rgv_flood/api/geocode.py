"""/api/v1/geocode: address search, proxied to Nominatim (OpenStreetMap).

The browser asks this app, not Nominatim, so the app can keep to Nominatim's
usage policy for everyone at once: it identifies itself, sends at most one
request a second, keeps answers for an hour, and limits each visitor to 30
searches a minute. Results are bounded to the four counties' box. Swapping
geocoders means changing RGV_GEOCODER_URL and `Geocoder._places`.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, defaultdict, deque
from typing import Annotated

import httpx2
from fastapi import APIRouter, HTTPException, Query, Request

from rgv_flood.api.models import Place
from rgv_flood.counties import RGV_BBOX

router = APIRouter()

UNAVAILABLE = "Search is unavailable right now"
CACHE_SECONDS = 3600
CACHE_ENTRIES = 512
CLIENT_LIMIT = 30  # searches per client per rolling minute


class Geocoder:
    def __init__(self, url: str, user_agent: str, *, transport=None, min_interval: float = 1.0, timeout: float = 5.0):
        self.url = url
        self.client = httpx2.Client(transport=transport, timeout=timeout, headers={"User-Agent": user_agent})
        self.min_interval = min_interval
        self._cache: OrderedDict[str, tuple[float, list[Place]]] = OrderedDict()
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _places(self, query: str) -> list[Place]:
        west, south, east, north = RGV_BBOX
        response = self.client.get(self.url, params={
            "q": query, "format": "jsonv2", "limit": 5, "countrycodes": "us",
            "viewbox": f"{west},{north},{east},{south}", "bounded": 1,
        })
        response.raise_for_status()
        return [Place(label=hit["display_name"], lon=float(hit["lon"]), lat=float(hit["lat"])) for hit in response.json()]

    def search(self, query: str) -> list[Place]:
        """Places matching `query`; raises httpx2 errors when the upstream fails."""
        key = " ".join(query.lower().split())
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        with self._lock:  # one upstream request at a time, at least min_interval apart
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                places = self._places(query)
            finally:
                self._last_request = time.monotonic()
        self._cache[key] = (time.monotonic() + CACHE_SECONDS, places)
        while len(self._cache) > CACHE_ENTRIES:
            self._cache.popitem(last=False)
        return places


class ClientLimiter:
    """At most `limit` calls per client in any 60 seconds."""

    def __init__(self, limit: int = CLIENT_LIMIT) -> None:
        self.limit = limit
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        calls = self._calls[client]
        while calls and calls[0] <= now - 60:
            calls.popleft()
        if len(calls) >= self.limit:
            return False
        calls.append(now)
        return True


def install(app) -> None:
    settings = app.state.settings
    app.state.geocoder = Geocoder(settings.geocoder_url, settings.geocoder_user_agent)
    app.state.geocode_limiter = ClientLimiter()


@router.get("/geocode", response_model=list[Place])
def geocode(request: Request, q: Annotated[str, Query(min_length=3, max_length=120)]):
    client = request.client.host if request.client else "unknown"
    if not request.app.state.geocode_limiter.allow(client):
        raise HTTPException(429, "Too many searches; try again in a minute")
    try:
        return request.app.state.geocoder.search(q)
    except httpx2.TimeoutException as error:
        raise HTTPException(504, UNAVAILABLE) from error
    except (httpx2.HTTPError, ValueError, KeyError) as error:
        raise HTTPException(502, UNAVAILABLE) from error
