import json

import pytest

from rgv_flood import create_app


@pytest.fixture()
def client(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "layers.json").write_text(json.dumps({"layers": []}))
    (data_dir / "closures.json").write_text(json.dumps({"reports": []}))
    app = create_app(
        {
            "TESTING": True,
            "MAP_DATA_DIR": data_dir,
            "CLOSURES_FILE": data_dir / "closures.json",
        }
    )
    return app.test_client()


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"RGV Flood Impact Visualizer" in res.data
    assert b"Not for flood-insurance" in res.data


def test_all_four_counties_in_selector(client):
    body = client.get("/").data
    for name in (b"Cameron County", b"Hidalgo County", b"Starr County", b"Willacy County"):
        assert name in body


def test_closures_partial_empty(client):
    res = client.get("/partials/closures")
    assert res.status_code == 200
    assert b"No reviewed reports" in res.data


def test_unknown_county_is_404(client):
    assert client.get("/partials/closures?county_slug=nueces").status_code == 404


def test_missing_layer_is_404(client):
    assert client.get("/api/layers/nope.geojson").status_code == 404
