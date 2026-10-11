#!/usr/bin/env python3
"""Give every RGV county the same provenance-first collection layout: a
`manifest.json`, its `schemas/`, a `records/` + `sources/` skeleton, and (for
the flood-hazard source notes) county-specific provenance JSON.

`data/<county>-county/` is entirely build output — none of it is committed
(see the repo `.gitignore` and README "Raw per-county data"). This script must
therefore be able to lay it down from nothing on a bare clone, which is why the
two schema files it copies into every county live in the tracked
`pipeline/schemas/` template, not in any county's own (gitignored) directory.

It never overwrites a hand-written `manifest.json`, `README.md`, or an existing
source note — those are only created when missing. Schema files and `.gitkeep`
placeholders are always refreshed. Does not touch the Flask app.

Run:  uv run python pipeline/scaffold_county_collections.py
Safe to re-run.
"""

from __future__ import annotations

import json
from pathlib import Path

from paths import DATA_DIR, county_dir
from paths import SCHEMA_DIR as SCHEMA_TEMPLATE_DIR  # tracked; see module docstring

from rgv_flood.counties import COUNTIES, NFHL_COUNTIES, SHORT_NAMES

RECORD_SUBDIRS = ["events-and-public-reports", "layers-and-weather"]
SOURCE_FAMILIES = [
    ("official-events", "Historical documented flood events and official incident or disaster records."),
    ("weather", "Weather observations and rainfall or event data."),
    ("terrain-hydrography", "Terrain, elevation, hydrography, and drainage-related layers."),
    ("flood-susceptibility", "Flood-susceptibility and reference layers."),
    ("public-reports", "Local news and permitted public Facebook, Instagram, and X material."),
    ("infrastructure-closures", "Public roads, drainage infrastructure, closures, and service reports."),
]


def _write_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _manifest(name: str, slug: str) -> str:
    data = {
        "manifest_version": "1.0.0",
        "dataset_id": f"{slug}-county-flood-evidence",
        "title": f"{name} County Flood Evidence Collection",
        "status": "collection_scaffold",
        "purpose": (
            "Shared collection of flood events, flood susceptibility, weather, terrain, "
            "public reports, and public infrastructure or closure evidence for the initial "
            "project dataset."
        ),
        "geography": {
            "name": f"{name} County, Texas",
            "boundary_policy": (
                f"Include an event when its claimed location is in {name} County or its "
                f"documented footprint overlaps {name} County."
            ),
        },
        "temporal_coverage": {"start": "2000-01-01", "end": "present"},
        "record_policy": {
            "shared_collection": True,
            "source_type_is_acceptance_tier": False,
            "preserve_provenance": True,
            "link_likely_duplicates": True,
            "do_not_silently_delete_duplicates": True,
        },
        "record_sets": [
            {
                "id": "events-and-public-reports",
                "path": "records/events-and-public-reports",
                "format": "ndjson",
                "schema": "schemas/event-public-report.schema.json",
                "description": "Documented flood events and supplementary public reports.",
            },
            {
                "id": "layers-and-weather",
                "path": "records/layers-and-weather",
                "format": "ndjson",
                "schema": "schemas/layer-weather-observation.schema.json",
                "description": "Static/reference layers and weather-observation datasets.",
            },
        ],
        "source_families": [
            {"id": fid, "path": f"sources/{fid}", "description": desc}
            for fid, desc in SOURCE_FAMILIES
        ],
        "processed_layers": {
            "path": "flood-hazard-layers",
            "description": (
                "Map-ready GeoJSON imported from the earlier Flood Project working "
                "directory; see flood-hazard-layers/manifest.json."
            ),
        },
        "primary_discovery_sources": [
            "NOAA NCEI Storm Events Database",
            "FEMA disaster declarations and local agency records",
            "NOAA NCEI Daily Summaries and Local Climatological Data",
            "USGS 3DEP and 3D Hydrography Program",
            "FEMA National Flood Hazard Layer",
            "TWDB Flood Planning Data Hub and Lower Rio Grande Region 15 materials",
            "Hidalgo County Drainage District No. 1 and local government public records",
        ],
    }
    return json.dumps(data, indent=2) + "\n"


def _readme(name: str) -> str:
    return f"""# {name} County dataset

This directory is the shared collection for {name} County data acquisition. It
covers 1 January 2000 through the present and mirrors the layout of
`data/hidalgo-county/`. It is a collection scaffold, not a prediction dataset and
not a statement that every retained claim is true.

## Layout

- `manifest.json` defines scope, source-family directories, and the collection policy.
- `schemas/` contains the validation contracts for the two record classes.
- `records/events-and-public-reports/` holds one JSON object per line for documented
  flood events and supplementary public reports.
- `records/layers-and-weather/` holds one JSON object per line for static/reference
  layers and weather-observation datasets.
- `sources/` holds source-specific acquisition notes, grouped by source family.
- `flood-hazard-layers/` holds map-ready GeoJSON (FEMA NFHL or the Hidalgo legacy
  FIRM, TWDB modeled extent, and the county boundary) imported from the earlier
  Flood Project working directory. See `flood-hazard-layers/manifest.json`.

## Collection rules

Validate each line in `records/events-and-public-reports/` against
`schemas/event-public-report.schema.json`, and each line in
`records/layers-and-weather/` against `schemas/layer-weather-observation.schema.json`.
Preserve the original source reference and stated precision. Use `unknown` or `null`
where appropriate; do not infer a coordinate, event extent, or timestamp.

Public social material must be public, accessible through permitted collection methods,
and limited to what is necessary for this project. Do not collect private material or
bypass platform access controls.
"""


def _tiger_source_note(name: str, geoid: str) -> str:
    return json.dumps({
        "publisher": "U.S. Census Bureau",
        "dataset": "TIGER/Line 2023 - Counties",
        "acquired_via": "Imported from Flood Project (data/raw/rgv_counties.geojson), originally TIGER 2023 county shapefile filtered to the RGV FIPS.",
        "source_landing_page": "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
        "query": {"where": f"GEOID='{geoid}'", "return_geometry": True},
        "result": {"feature_count": 1, "geoid": geoid, "name": f"{name} County"},
        "stored_at": "flood-hazard-layers/boundary.geojson",
        "license_or_terms_note": "Public Census geographic reference service. The boundary is a study-area reference and must not be presented as flood evidence.",
    }, indent=2) + "\n"


def _fema_source_note(slug: str) -> str:
    return json.dumps({
        "publisher": "Federal Emergency Management Agency",
        "dataset": "National Flood Hazard Layer (NFHL)",
        "acquired_via": f"Imported from Flood Project (data/raw/nfhl_{slug}.geojson), pulled from FEMA's ArcGIS REST MapServer layer 28 (Flood Hazard Zones) by bounding-box query.",
        "source_landing_page": "https://www.fema.gov/flood-maps/products-tools/national-flood-hazard-layer",
        "service_endpoint": "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28",
        "fields_of_interest": ["DFIRM_ID", "FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "STATIC_BFE", "DEPTH", "VELOCITY", "SOURCE_CIT"],
        "stored_at": "flood-hazard-layers/fema-nfhl.geojson",
        "caveats": [
            "Bounding-box download: a few polygons from neighboring counties can spill in; clip to boundary.geojson before use.",
            "Effective regulatory layer, but not a substitute for an official property-level determination.",
        ],
        "license_or_terms_note": "FEMA NFHL is the preferred effective-hazard source where coverage is available.",
    }, indent=2) + "\n"


def _twdb_source_note() -> str:
    return json.dumps({
        "publisher": "Texas Water Development Board",
        "dataset": "2025 Cursory Floodplain Dataset (Fathom 3m combined peril, Scenario 5 existing conditions)",
        "acquired_via": "Imported from Flood Project (data/raw/twdb_cursory_1in100_rgv.geojson / _1in500_rgv.geojson); extracted from the statewide smoothed geodatabase, Region 15, clipped to county boundaries.",
        "source_landing_page": "https://twdb-flood-planning-resources-twdb.hub.arcgis.com/pages/cursory-floodplain-data-2025",
        "frequencies": {"1in100": "1% annual chance", "1in500": "0.2% annual chance"},
        "stored_at": [
            "flood-hazard-layers/twdb-cursory-1in100.geojson",
            "flood-hazard-layers/twdb-cursory-1in500.geojson",
        ],
        "license_or_terms_note": "TWDB public planning data. Modeled and contextual; NOT an effective FEMA flood insurance regulatory layer.",
    }, indent=2) + "\n"


def _hcdd1_source_note() -> str:
    return json.dumps({
        "publisher": "Hidalgo County Drainage District No. 1",
        "dataset": "Digitized copy of the 1981 Hidalgo County FIRM (HidalgoFIRM)",
        "acquired_via": "Imported from Flood Project (data/raw/hidalgo_firm_hcdd1.geojson), paged from the FeatureServer; zone labels resolved from the layer's drawingInfo renderer.",
        "source_landing_page": "https://www.hcdd1.org/page/floodplains",
        "service_endpoint": "https://services7.arcgis.com/JSUhwVSJhyVkcN3Q/arcgis/rest/services/FloodMapService/FeatureServer/0",
        "stored_at": "flood-hazard-layers/hcdd1-firm-1981.geojson",
        "caveats": [
            "The only flood-zone dataset that exists for Hidalgo County; FEMA has no digital NFHL coverage here.",
            "1981 base map (some zones later revised by LOMR); urban core largely undrawn.",
            "Zone semantics not confirmed equivalent to current FEMA classes.",
        ],
        "license_or_terms_note": "Public local-government flood map service. Legacy local reference, not an effective FEMA determination.",
    }, indent=2) + "\n"


def _source_notes(slug: str, name: str, geoid: str) -> dict[str, str]:
    """Provenance notes for the imported flood-hazard layers, by path under sources/."""
    notes = {
        f"terrain-hydrography/us-census-tigerweb-{slug}-county-2026.json": _tiger_source_note(name, geoid),
        f"flood-susceptibility/twdb-cursory-floodplain-{slug}-county-2026.json": _twdb_source_note(),
    }
    if slug in NFHL_COUNTIES:
        notes[f"flood-susceptibility/fema-nfhl-{slug}-county-2026.json"] = _fema_source_note(slug)
    else:
        notes["flood-susceptibility/hcdd1-firm-1981-hidalgo-county.json"] = _hcdd1_source_note()
    return notes


def scaffold_county(slug: str, data_dir: Path, schema_files: list[Path]) -> list[str]:
    """Lay down one county's folders and files; returns what was newly created."""
    root = county_dir(slug, data_dir)
    name, geoid = SHORT_NAMES[slug], COUNTIES[slug]["fips"]

    # Schemas are always refreshed from the tracked template: every county,
    # Hidalgo included, is just a copy, and none of them is itself the source.
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    for schema in schema_files:
        (root / "schemas" / schema.name).write_text(schema.read_text(encoding="utf-8"), encoding="utf-8")

    # Empty record/source folders get a .gitkeep so they exist on a fresh clone.
    keep = [root / "records" / sub for sub in RECORD_SUBDIRS] + [root / "sources" / fid for fid, _ in SOURCE_FAMILIES]
    for directory in keep:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").touch()

    # Never overwrite a hand-written manifest, README or source note.
    files = {"manifest.json": _manifest(name, slug), "README.md": _readme(name)}
    files |= {f"sources/{path}": text for path, text in _source_notes(slug, name, geoid).items()}
    return [relative for relative, text in files.items() if _write_if_missing(root / relative, text)]


def main(data_dir: Path = DATA_DIR) -> None:
    schema_files = list(SCHEMA_TEMPLATE_DIR.glob("*.schema.json"))
    if not schema_files:
        raise SystemExit(f"no schema files under {SCHEMA_TEMPLATE_DIR}")

    for slug in COUNTIES:
        created = scaffold_county(slug, data_dir, schema_files)
        print(f"[{slug}] scaffold ok" + (f" - created: {', '.join(created)}" if created else " - already complete"))


if __name__ == "__main__":
    main()
