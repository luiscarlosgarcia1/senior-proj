"""The one place a map layer file is written."""

from __future__ import annotations

from paths import OUT_DIR


def write_layer(filename: str, geojson: str, feature_count: int) -> int:
    """Write one layer file for the Flask app to serve, and report its size."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    path.write_text(geojson, encoding="utf-8")
    print(f"  {filename}: {feature_count} features, {path.stat().st_size / 1024:,.0f} KB")
    return feature_count
