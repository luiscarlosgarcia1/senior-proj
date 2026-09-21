"""Application configuration.

Values are read-mostly for the initial four-county scope. No secrets belong
here; anything sensitive should come from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent


class Default:
    # Where the pipeline writes map-ready GeoJSON that the app serves as-is.
    MAP_DATA_DIR = Path(
        os.environ.get("RGV_MAP_DATA_DIR", _PACKAGE_ROOT / "static" / "data")
    )

    # Overlays built from the ingested NOAA records (pipeline/build_events.py).
    FLOOD_EVENTS_FILE = MAP_DATA_DIR / "flood-events.geojson"
    FLOOD_REPORTS_FILE = MAP_DATA_DIR / "flood-reports.json"
    RAINFALL_FILE = MAP_DATA_DIR / "rainfall-records.json"
    LIVE_SIGNALS_DATABASE = Path(
        os.environ.get("RGV_LIVE_SIGNALS_DATABASE", _PACKAGE_ROOT.parents[1] / "data" / "generated" / "live-signals.sqlite3")
    )

    # Initial Leaflet view: centered on the Lower Rio Grande Valley.
    MAP_CENTER = (26.3, -98.15)
    MAP_ZOOM = 9

    JSON_SORT_KEYS = False
