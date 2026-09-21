import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from drivetexas import DRIVE_TEXAS_LAYERS, ingest_drivetexas_snapshot
from live_signals import LiveSignalStore

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
HIDALGO = {
    "type": "Polygon",
    "coordinates": [[[-98.5, 26.0], [-98.0, 26.0], [-98.0, 26.5], [-98.5, 26.5], [-98.5, 26.0]]],
}


def _feature(object_id: int, geometry: dict, **attributes: object) -> dict:
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "OBJECTID": object_id,
            "TXDOT_COUNTY_NBR": 108,
            "CNSTRNT_TYPE_CD": "F",
            "COND_DESC": "Water over roadway",
            **attributes,
        },
    }


def test_full_paginated_snapshot_persists_only_intersecting_source_geometries(
    tmp_path: Path,
) -> None:
    pages = {
        (DRIVE_TEXAS_LAYERS[0].key, 0): {
            "features": [_feature(1, {"type": "Point", "coordinates": [-98.2, 26.2]})],
            "exceededTransferLimit": True,
        },
        (DRIVE_TEXAS_LAYERS[0].key, 1): {
            "features": [_feature(2, {"type": "Point", "coordinates": [-97.7, 26.2]})],
            "exceededTransferLimit": False,
        },
        (DRIVE_TEXAS_LAYERS[1].key, 0): {
            "features": [_feature(3, {"type": "LineString", "coordinates": [[-98.4, 26.1], [-98.1, 26.4]]})],
            "exceededTransferLimit": False,
        },
    }

    def fetch(layer, offset):
        return pages[(layer.key, offset)]

    store = LiveSignalStore(tmp_path / "signals.sqlite3")
    result = ingest_drivetexas_snapshot(
        store, {"hidalgo": HIDALGO}, fetch_page=fetch, retrieved_at=NOW
    )

    assert result.inserted == 2
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "select source, native_id, county_slugs_json, source_attributes_json from live_signals order by native_id"
        ).fetchall()
    assert [row[:3] for row in rows] == [
        ("drivetexas:points", "1", '["hidalgo"]'),
        ("drivetexas:lines", "3", '["hidalgo"]'),
    ]
    assert '"CNSTRNT_TYPE_CD":"F"' in rows[0][3]


def test_incomplete_layer_snapshot_does_not_reconcile_existing_observations(
    tmp_path: Path,
) -> None:
    store = LiveSignalStore(tmp_path / "signals.sqlite3")
    complete_pages = {
        (DRIVE_TEXAS_LAYERS[0].key, 0): {
            "features": [_feature(1, {"type": "Point", "coordinates": [-98.2, 26.2]})]
        },
        (DRIVE_TEXAS_LAYERS[1].key, 0): {"features": []},
    }
    ingest_drivetexas_snapshot(
        store,
        {"hidalgo": HIDALGO},
        fetch_page=lambda layer, offset: complete_pages[(layer.key, offset)],
        retrieved_at=NOW,
    )

    def failed_fetch(layer, offset):
        if layer.key == "points":
            raise OSError("upstream unavailable")
        return {"features": []}

    result = ingest_drivetexas_snapshot(
        store, {"hidalgo": HIDALGO}, fetch_page=failed_fetch, retrieved_at=NOW
    )

    assert result.inserted == result.updated == result.terminalized == 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("select lifecycle_state from live_signals").fetchone() == ("active",)

