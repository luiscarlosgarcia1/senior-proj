"""Assemble the layer manifest the Flask app reads.

Scans the map-data directory for the GeoJSON files produced by the ingest
scripts and writes layers.json. Extend LAYER_SPECS as ingest scripts land.
"""

from __future__ import annotations

import json
from pathlib import Path

MAP_DATA_DIR = Path(__file__).resolve().parents[1] / "src" / "rgv_flood" / "static" / "data"

LAYER_SPECS: list[dict] = [
    {
        "id": "county-boundaries",
        "file": "county-boundaries.geojson",
        "title": "County boundaries",
        "source": "US Census TIGER/Line",
        "vintage": "2024",
        "hazard_type": "n/a (study-area reference)",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": "Geographic reference only. Not flood evidence.",
        "source_url": "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    },
    {
        "id": "fema-nfhl",
        "file": "fema-nfhl.geojson",
        "title": "FEMA effective flood hazard (NFHL)",
        "source": "FEMA NFHL",
        "vintage": "effective date varies by panel",
        "hazard_type": "effective regulatory flood hazard",
        "coverage": "Cameron, Starr, Willacy",
        "limitation": "No digital NFHL coverage for Hidalgo County. Not a property-level determination.",
        "source_url": "https://msc.fema.gov/portal/home",
    },
    {
        "id": "hidalgo-dd1-1981",
        "file": "hidalgo-dd1-1981.geojson",
        "title": "Hidalgo County historic flood zones (1981)",
        "source": "Hidalgo County DD No. 1 digitized 1981 map",
        "vintage": "1981",
        "hazard_type": "historic local flood-zone reference",
        "coverage": "Hidalgo",
        "limitation": "44-year-old map. May not reflect current development or newer studies. Zone semantics not confirmed equivalent to FEMA classes.",
        "source_url": "",
    },
    {
        "id": "twdb-cursory",
        "file": "twdb-cursory.geojson",
        "title": "TWDB modeled flood extent (2025 cursory)",
        "source": "TWDB 2025 cursory floodplain",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
]


def main() -> None:
    layers = [spec for spec in LAYER_SPECS if (MAP_DATA_DIR / spec["file"]).exists()]
    manifest = {"generated_by": "pipeline/build_layers.py", "layers": layers}
    (MAP_DATA_DIR / "layers.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(layers)} layer(s) to layers.json")


if __name__ == "__main__":
    main()
