"""Browser tests: the real app, served by Uvicorn on a free port, in Chromium.

The fixture database gets real map data where the browser needs it: county
outlines, a FEMA hazard polygon, and genuine vector tiles for the tiled TWDB
layer. Basemaps point at the app's offline style, so no test needs the network.
"""

from __future__ import annotations

import gzip
import json
import socket
import threading
import time

import pytest
import uvicorn
from browser_support import wait_js
from database import open_database, replace_table
from fixture_db import LAYERS, build_fixture_database

pytest.importorskip("pyogrio", reason="tiles need the pipeline dependency group")

import layer_tiles

from rgv_flood import assets, vendor
from rgv_flood.app import create_app
from rgv_flood.settings import Settings

OFFLINE = "/static/basemap/offline.json"
COUNTY_BOXES = {
    "Cameron": (-97.86, 25.84, -97.15, 26.40),
    "Hidalgo": (-98.59, 26.05, -97.86, 26.78),
    "Starr": (-99.17, 26.20, -98.59, 26.78),
    "Willacy": (-97.95, 26.33, -97.30, 26.60),
}


def _box(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}


def _collection(features):
    return json.dumps({"type": "FeatureCollection", "features": features})


COUNTIES = _collection([
    {"type": "Feature", "properties": {"county": name}, "geometry": _box(*box)} for name, box in COUNTY_BOXES.items()
])
HAZARD = _collection([{
    "type": "Feature", "geometry": _box(-98.3, 26.1, -98.1, 26.3),
    "properties": {"source": "FEMA NFHL", "original_category": "AE", "relative_class": "high", "county": "Hidalgo"},
}])
TWDB_SQUARE = _collection([{
    "type": "Feature", "geometry": _box(-98.25, 26.15, -98.15, 26.25),
    "properties": {"source": "TWDB", "original_category": "1% annual chance", "relative_class": "high"},
}])


def browser_layers() -> list[dict]:
    by_id = {row["id"]: dict(row) for row in LAYERS}
    by_id["county-boundaries"]["geojson_gzip"] = gzip.compress(COUNTIES.encode())
    by_id["fema-nfhl"]["geojson_gzip"] = gzip.compress(HAZARD.encode())
    by_id["twdb-cursory-1in100"]["geojson_gzip"] = gzip.compress(TWDB_SQUARE.encode())
    return [*by_id.values()]


@pytest.fixture(scope="session")
def browser_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("browser")
    database = build_fixture_database(folder / "rgv-flood.sqlite3", history=True)
    tiles = layer_tiles.cut_tiles("twdb-cursory-1in100", TWDB_SQUARE, folder)
    with open_database(database) as connection:
        replace_table(connection, "layers", browser_layers())
        replace_table(connection, "layer_tiles", [
            {"layer_id": "twdb-cursory-1in100", "z": z, "x": x, "y": y, "data": data} for z, x, y, data in tiles
        ])
    return database


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(browser_db):
    vendor.fetch_all()
    assets.build_css(minify=False)
    app = create_app(Settings(
        database=browser_db, live_signals_scheduler_enabled=False,
        basemap_light_style=OFFLINE, basemap_dark_style=OFFLINE,
    ))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def console_errors(page):
    """Every console error and uncaught page error; tests assert it stays empty."""
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors


@pytest.fixture()
def map_page(page, live_server, console_errors):
    """The map page, loaded, with the map ready (window.__rgvMap exposed by ?test=1)."""

    def open_(hash_: str = ""):
        page.goto(f"{live_server}/?test=1{hash_}")
        wait_js(page, "window.__rgvMap && window.__rgvMap.isStyleLoaded()")
        return page

    return open_

