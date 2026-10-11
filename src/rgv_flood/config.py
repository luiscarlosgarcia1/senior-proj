"""Application configuration.

Values are read-mostly for the initial four-county scope. No secrets belong
here; anything sensitive should come from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

# The database is build output: outside the package, under the repository's data/generated/.
_GENERATED = Path(__file__).resolve().parents[2] / "data" / "generated"


class Default:
    # The one database the app reads: map layers, flood events, reports and
    # weather built by pipeline/build_all.py, plus the live signals the
    # scheduler refreshes while the app runs.
    DATABASE = Path(os.environ.get("RGV_DATABASE", _GENERATED / "rgv-flood.sqlite3"))
    LIVE_SIGNALS_SCHEDULER_ENABLED = (
        os.environ.get("RGV_LIVE_SIGNALS_SCHEDULER_ENABLED", "true").lower() == "true"
    )
    LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS = int(
        os.environ.get("RGV_LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS", "900")
    )
    LIVE_SIGNALS_SCHEDULER_LOCK_FILE = Path(
        os.environ.get(
            "RGV_LIVE_SIGNALS_SCHEDULER_LOCK_FILE",
            DATABASE.parent / ".live-signals-scheduler.lock",
        )
    )

    # Initial Leaflet view: centered on the Lower Rio Grande Valley.
    MAP_CENTER = (26.3, -98.15)
    MAP_ZOOM = 9
