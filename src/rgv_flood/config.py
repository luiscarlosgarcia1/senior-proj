"""Application configuration.

Values are read-mostly for the initial four-county scope. No secrets belong
here; anything sensitive should come from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

# Build outputs live outside the package, under the repository's data/generated/.
_GENERATED = Path(__file__).resolve().parents[2] / "data" / "generated"


class Default:
    # Map layers, flood events, reports and rainfall, built by pipeline/build_all.py.
    APP_DATABASE = Path(os.environ.get("RGV_APP_DATABASE", _GENERATED / "rgv-flood.sqlite3"))
    # Current official signals, refreshed by the scheduler while the app runs.
    LIVE_SIGNALS_DATABASE = Path(os.environ.get("RGV_LIVE_SIGNALS_DATABASE", _GENERATED / "live-signals.sqlite3"))
    LIVE_SIGNALS_SCHEDULER_ENABLED = (
        os.environ.get("RGV_LIVE_SIGNALS_SCHEDULER_ENABLED", "true").lower() == "true"
    )
    LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS = int(
        os.environ.get("RGV_LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS", "900")
    )
    LIVE_SIGNALS_SCHEDULER_LOCK_FILE = Path(
        os.environ.get(
            "RGV_LIVE_SIGNALS_SCHEDULER_LOCK_FILE",
            LIVE_SIGNALS_DATABASE.parent / ".live-signals-scheduler.lock",
        )
    )

    # Initial Leaflet view: centered on the Lower Rio Grande Valley.
    MAP_CENTER = (26.3, -98.15)
    MAP_ZOOM = 9
