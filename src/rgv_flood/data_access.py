"""Read-only access to pipeline outputs.

The app serves what the offline pipeline produced. It does not fetch from FEMA,
TWDB, Census, or news sites at request time.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from flask import current_app


def _map_data_dir() -> Path:
    return Path(current_app.config["MAP_DATA_DIR"])


def available_layers() -> list[dict]:
    """Layer manifest written by the pipeline: id, title, source, vintage, file."""
    manifest = _map_data_dir() / "layers.json"
    if not manifest.exists():
        return []
    return json.loads(manifest.read_text(encoding="utf-8")).get("layers", [])


def layer_geojson(layer_id: str) -> dict | None:
    for layer in available_layers():
        if layer["id"] == layer_id:
            path = _map_data_dir() / layer["file"]
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
    return None


@lru_cache(maxsize=1)
def _load_closures(path_str: str, mtime: float) -> list[dict]:
    return json.loads(Path(path_str).read_text(encoding="utf-8")).get("reports", [])


def closure_reports(county_slug: str | None = None) -> list[dict]:
    """Manually reviewed historical road-closure reports.

    Never live data. Each report carries its source article URL and publication
    date; unresolved records are kept but flagged.
    """
    path = Path(current_app.config["CLOSURES_FILE"])
    if not path.exists():
        return []
    reports = _load_closures(str(path), path.stat().st_mtime)
    if county_slug:
        reports = [r for r in reports if r.get("county") == county_slug]
    return reports
