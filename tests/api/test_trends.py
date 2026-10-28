"""API: /api/v1/trends — the time series behind the trends page."""

from datetime import UTC, datetime

WESLACO = "USC00419588"


def test_trends_returns_all_series(api_client):
    body = api_client.get("/api/v1/trends").json()

    assert set(body) == {
        "stations", "station", "rain_years", "rain_months", "events_by_year", "nws_by_year", "news_by_year",
        "news_first_year",
    }
    assert body["station"] is None
    assert [s["name"] for s in body["stations"]] == ["McAllen Airport", "Rio Grande City", "Weslaco"]
    assert body["events_by_year"][-1]["year"] == datetime.now(UTC).year - 1  # the current year isn't over
    assert {y["year"]: y["total"] for y in body["events_by_year"]}[2020] == 1
    assert body["news_first_year"] == 2018


def test_trends_station_param(api_client):
    body = api_client.get("/api/v1/trends", params={"county": "hidalgo", "station": WESLACO}).json()

    assert body["station"] == WESLACO
    assert [(y["year"], y["inches"]) for y in body["rain_years"]] == [(2020, 10.0)]
    assert {m["month"]: m["inches"] for m in body["rain_months"]} == {6: 2.0, 7: 5.0, 8: None}


def test_trends_station_in_the_wrong_county_404(api_client):
    response = api_client.get("/api/v1/trends", params={"county": "starr", "station": WESLACO})

    assert response.status_code == 404


def test_trends_unknown_station_404(api_client):
    assert api_client.get("/api/v1/trends", params={"station": "NOPE"}).status_code == 404


def test_trends_bad_county_422(api_client):
    assert api_client.get("/api/v1/trends", params={"county": "texas"}).status_code == 422


def test_trends_etag_returns_304(api_client):
    first = api_client.get("/api/v1/trends")

    again = api_client.get("/api/v1/trends", headers={"If-None-Match": first.headers["etag"]})

    assert again.status_code == 304
