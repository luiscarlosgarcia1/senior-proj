"""Paths shared by the layer builders, and the one place a layer file is written."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COUNTY_DIR = REPO_ROOT / "data"
ML_RAW = COUNTY_DIR / "ml" / "raw"
OUT_DIR = REPO_ROOT / "src" / "rgv_flood" / "static" / "data"


def write_layer(filename: str, geojson: str, feature_count: int) -> int:
    """Write one layer file for the Flask app to serve, and report its size."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    path.write_text(geojson, encoding="utf-8")
    print(f"  {filename}: {feature_count} features, {path.stat().st_size / 1024:,.0f} KB")
    return feature_count
