"""API: /api/v1/geocode, the address-search proxy in front of Nominatim."""

import httpx2

from rgv_flood.api.geocode import Geocoder
from rgv_flood.counties import RGV_BBOX

NOMINATIM = [{"display_name": "1200 W University Dr, Edinburg, Texas", "lat": "26.3049", "lon": "-98.1735"}]


def _use(client, handler):
    calls = []

    def record(request):
        calls.append(request)
        return handler(request)

    client.app.state.geocoder = Geocoder(
        "https://nominatim.example/search", "Test-Agent/1.0", transport=httpx2.MockTransport(record), min_interval=0
    )
    return calls


def test_geocode_returns_places(api_client):
    _use(api_client, lambda request: httpx2.Response(200, json=NOMINATIM))

    response = api_client.get("/api/v1/geocode", params={"q": "1200 W University Dr Edinburg"})

    assert response.status_code == 200
    assert response.json() == [{"label": "1200 W University Dr, Edinburg, Texas", "lon": -98.1735, "lat": 26.3049}]


def test_geocode_sends_user_agent_and_bbox(api_client):
    calls = _use(api_client, lambda request: httpx2.Response(200, json=[]))

    api_client.get("/api/v1/geocode", params={"q": "Weslaco"})

    (request,) = calls
    west, south, east, north = RGV_BBOX
    assert request.headers["user-agent"] == "Test-Agent/1.0"
    assert request.url.params["viewbox"] == f"{west},{north},{east},{south}"
    assert request.url.params["bounded"] == "1"
    assert request.url.params["countrycodes"] == "us"
    assert request.url.params["format"] == "jsonv2"
    assert request.url.params["limit"] == "5"


def test_geocode_cached(api_client):
    calls = _use(api_client, lambda request: httpx2.Response(200, json=NOMINATIM))

    api_client.get("/api/v1/geocode", params={"q": "Edinburg"})
    api_client.get("/api/v1/geocode", params={"q": "  edinburg "})

    assert len(calls) == 1


def test_geocode_rate_limited_429(api_client):
    _use(api_client, lambda request: httpx2.Response(200, json=[]))

    statuses = [api_client.get("/api/v1/geocode", params={"q": "Edinburg"}).status_code for _ in range(31)]

    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429


def test_geocode_upstream_failure_is_502(api_client):
    _use(api_client, lambda request: httpx2.Response(503, text="busy"))

    response = api_client.get("/api/v1/geocode", params={"q": "Edinburg"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Search is unavailable right now"}


def test_geocode_timeout_504(api_client):
    def slow(request):
        raise httpx2.ReadTimeout("too slow", request=request)

    _use(api_client, slow)

    response = api_client.get("/api/v1/geocode", params={"q": "Edinburg"})

    assert response.status_code == 504
    assert response.json() == {"detail": "Search is unavailable right now"}


def test_geocode_short_query_422(api_client):
    assert api_client.get("/api/v1/geocode", params={"q": "ab"}).status_code == 422
