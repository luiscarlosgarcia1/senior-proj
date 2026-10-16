"""API: flood events, one event's context, rainfall records, curated reports."""


def test_events_filtered_by_county_and_year(api_client):
    everything = api_client.get("/api/v1/events").json()
    one_year = api_client.get("/api/v1/events", params={"year": 2018}).json()
    cameron = api_client.get("/api/v1/events", params={"county": "cameron"}).json()

    assert everything["total"] == 2
    assert [e["id"] for e in everything["events"]] == ["noaa-storm-events-1", "noaa-storm-events-2"]
    assert everything["years"] == [2020, 2018]
    assert everything["types"] == ["Flash flood", "Flood"]
    assert [e["id"] for e in one_year["events"]] == ["noaa-storm-events-2"]
    assert one_year["total"] == 2  # the count before filters
    assert cameron["events"] == []


def test_events_filtered_by_type(api_client):
    body = api_client.get("/api/v1/events", params={"type": "Flash flood"}).json()

    assert [e["id"] for e in body["events"]] == ["noaa-storm-events-1"]


def test_events_bad_county_422(api_client):
    assert api_client.get("/api/v1/events", params={"county": "texas"}).status_code == 422


def test_events_geojson_only_plottable(api_client):
    features = api_client.get("/api/v1/events.geojson").json()["features"]

    assert [f["properties"]["id"] for f in features] == ["noaa-storm-events-1"]
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [-98.2, 26.2]}


def test_event_context_rain_nearest_first(api_client):
    context = api_client.get("/api/v1/events/noaa-storm-events-1/context").json()

    assert context["event"]["id"] == "noaa-storm-events-1"
    assert [g["name"] for g in context["rain"]["gauges"]][:2] == ["McAllen Airport", "Weslaco"]
    assert [d["label"] for d in context["rain"]["days"]] == ["Jul 24", "Jul 25", "Jul 26"]
    assert [d["began"] for d in context["rain"]["days"]] == [False, True, False]
    assert context["rain"]["gauges"][0]["inches"] == [None, 1.0, None]
    assert [r["id"] for r in context["reports"]] == ["hanna-landfall", "hanna-recovery"]


def test_event_context_includes_nws_reports(api_client):
    context = api_client.get("/api/v1/events/noaa-storm-events-1/context").json()

    assert [r["id"] for r in context["nws_reports"]] == ["nws-1"]  # same county, same days; not Cameron's


def test_event_context_unknown_404(api_client):
    assert api_client.get("/api/v1/events/nope/context").status_code == 404


def test_rainfall_records_ranked(api_client):
    records = api_client.get("/api/v1/rainfall-records").json()

    assert [r["inches"] for r in records][:3] == [8.6, 5.0, 2.0]
    assert records[0] == {"county": "hidalgo", "date": "2025-03-28", "station": "Weslaco", "mm": 218.4, "inches": 8.6}


def test_rainfall_records_by_county(api_client):
    records = api_client.get("/api/v1/rainfall-records", params={"county": "starr"}).json()

    assert [(r["station"], r["inches"]) for r in records] == [("Rio Grande City", 2.0)]


def test_reports_by_county(api_client):
    hidalgo = api_client.get("/api/v1/reports", params={"county": "hidalgo"}).json()

    assert [r["id"] for r in hidalgo] == ["hanna-landfall", "hanna-recovery", "weslaco-streets"]
    assert api_client.get("/api/v1/reports", params={"county": "willacy"}).json() == []
