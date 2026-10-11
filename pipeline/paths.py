"""Where everything lives: the one place the repo's data layout is spelled out."""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
ML_RAW = DATA_DIR / "ml" / "raw"  # public model inputs (fetch_ml_inputs.py)
NOAA_RAW = REPO_ROOT / "tmp" / "noaa"  # downloaded NOAA .csv.gz files
SCHEMA_DIR = REPO_ROOT / "pipeline" / "schemas"
APP_DB = DATA_DIR / "generated" / "rgv-flood.sqlite3"  # everything the Flask app serves (app_db.py)
LIVE_SIGNALS_DB = DATA_DIR / "generated" / "live-signals.sqlite3"
GEOPACKAGE = DATA_DIR / "generated" / "county-collections.gpkg"

# The earlier "Flood Project" working directory: the only source of the FEMA,
# TWDB and Hidalgo FIRM geometry (import_county_flood_data.py).
FLOOD_PROJECT_RAW = Path(
    os.environ.get(
        "RGV_FLOOD_PROJECT_RAW_DIR",
        "C:/Users/danny/Documents/Code Projects/Flood Project/data/raw",
    )
).resolve()


def county_dir(slug: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"{slug}-county"


def hazard_layers_dir(slug: str, data_dir: Path = DATA_DIR) -> Path:
    return county_dir(slug, data_dir) / "flood-hazard-layers"


def storm_events_file(slug: str, data_dir: Path = DATA_DIR) -> Path:
    """NOAA Storm Events records, plus any hand-curated public reports."""
    return county_dir(slug, data_dir) / "records" / "events-and-public-reports" / "noaa-storm-events.ndjson"


def ghcn_daily_file(slug: str, data_dir: Path = DATA_DIR) -> Path:
    return county_dir(slug, data_dir) / "records" / "layers-and-weather" / "noaa-ghcn-daily-2000-2025.ndjson"


def county_boundary(slug: str, data_dir: Path = DATA_DIR) -> dict:
    """The county's Census TIGER boundary as a GeoJSON geometry."""
    path = hazard_layers_dir(slug, data_dir) / "boundary.geojson"
    return json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"]
