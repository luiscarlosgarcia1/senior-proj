"""API: /api/v1/layers, layer GeoJSON and vector tiles."""

import gzip
import json

from fixture_db import PHOTOS_GEOJSON


def test_layers_grouped_in_order(api_client):
    body = api_client.get("/api/v1/layers").json()

    assert [g["id"] for g in body["groups"]] == ["hazard", "works", "evidence", "projects"]
    assert [g["title"] for g in body["groups"]] == ["Flood hazard", "Drainage & flood works", "Evidence of flooding", "Projects"]
    assert [layer["id"] for layer in body["base"]] == ["county-boundaries"]
    hazard = body["groups"][0]["layers"]
    assert [layer["id"] for layer in hazard] == ["fema-nfhl", "twdb-cursory-1in100", "twdb-cursory-1in500"]
    nfhl = hazard[0]
    assert nfhl["title"] == "FEMA effective flood hazard (NFHL)"
    assert nfhl["feature_count"] == 20
    assert nfhl["legend"] == {"shape": "poly", "color": "nfhl"}
    assert (nfhl["delivery"], nfhl["url"]) == ("geojson", "/api/v1/layers/fema-nfhl.geojson")


def test_twdb_rows_share_panel_row(api_client):
    hazard = api_client.get("/api/v1/layers").json()["groups"][0]["layers"]
    twdb = [layer for layer in hazard if layer["panel_row"] == "twdb"]

    assert [layer["short_label"] for layer in twdb] == ["1% annual chance", "0.2% annual chance"]
    assert {layer["row_label"] for layer in twdb} == {"TWDB modeled flood extent"}
    assert twdb[0]["delivery"] == "tiles"
    assert twdb[0]["url"] == "/api/v1/tiles/twdb-cursory-1in100/{z}/{x}/{y}.pbf?v=abc123def456"


def test_photo_parts_present(api_client):
    evidence = api_client.get("/api/v1/layers").json()["groups"][2]["layers"]
    photos = next(layer for layer in evidence if layer["id"] == "hcdd1-flood-photos")

    assert photos["parts"] == [
        {"id": "photos", "label": "Photos you can open", "filter": ["has", "photo_url"]},
        {"id": "locations", "label": "Photo locations only", "filter": ["!", ["has", "photo_url"]]},
    ]


def test_virtual_layers_in_evidence(api_client):
    evidence = api_client.get("/api/v1/layers").json()["groups"][2]["layers"]
    virtual = {layer["id"]: layer for layer in evidence if layer["delivery"] == "api"}

    assert virtual["noaa-flood-events"]["url"] == "/api/v1/events.geojson"
    assert virtual["noaa-flood-events"]["legend"] == {"shape": "dot", "color": "sev-high"}
    assert virtual["live-alerts"]["url"] == "/api/v1/live-signals.geojson"
    assert virtual["live-alerts"]["legend"] == {"shape": "dia", "color": "warn"}


def test_layer_geojson_gzip_passthrough(api_client):
    with api_client.stream("GET", "/api/v1/layers/hcdd1-flood-photos.geojson", headers={"Accept-Encoding": "gzip"}) as response:
        raw = b"".join(response.iter_raw())

    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=86400"
    assert raw == gzip.compress(PHOTOS_GEOJSON.encode())  # the stored bytes, not recompressed


def test_layer_geojson_plain_when_gzip_not_accepted(api_client):
    response = api_client.get("/api/v1/layers/hcdd1-flood-photos.geojson", headers={"Accept-Encoding": "identity"})

    assert "content-encoding" not in response.headers
    assert json.loads(response.content) == json.loads(PHOTOS_GEOJSON)


def test_layer_geojson_304(api_client):
    first = api_client.get("/api/v1/layers/hcdd1-flood-photos.geojson")

    second = api_client.get("/api/v1/layers/hcdd1-flood-photos.geojson", headers={"If-None-Match": first.headers["etag"]})

    assert second.status_code == 304


def test_layer_geojson_unknown_404(api_client):
    assert api_client.get("/api/v1/layers/nope.geojson").status_code == 404


def test_tile_served(api_client):
    with api_client.stream("GET", "/api/v1/tiles/twdb-cursory-1in100/10/232/434.pbf") as response:
        raw = b"".join(response.iter_raw())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert gzip.decompress(raw) == b"mvt"


def test_empty_tile_204(api_client):
    assert api_client.get("/api/v1/tiles/twdb-cursory-1in100/10/0/0.pbf").status_code == 204


def test_tile_out_of_range_422(api_client):
    assert api_client.get("/api/v1/tiles/twdb-cursory-1in100/10/1024/0.pbf").status_code == 422
    assert api_client.get("/api/v1/tiles/twdb-cursory-1in100/23/0/0.pbf").status_code == 422


def test_tile_of_untiled_layer_404(api_client):
    assert api_client.get("/api/v1/tiles/fema-nfhl/10/232/434.pbf").status_code == 404


def test_layers_before_build_is_empty(make_client, tmp_path):
    assert make_client(tmp_path / "not-built.sqlite3").get("/api/v1/layers").json() == {"base": [], "groups": []}
