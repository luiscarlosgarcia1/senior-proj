#!/usr/bin/env python3
"""One command, start to finish: scaffold the county collections, download and
ingest the NOAA source data for all four counties, and build the local query
GeoPackage.

`data/<county>-county/` is entirely gitignored build output (see the repo
README, "Raw per-county data") -- on a bare clone this is the script that
produces it. Steps, in order:

  1. scripts/scaffold_county_collections.py   manifest, schemas, folder skeleton
  2. scripts/download-noaa-source-files.mjs   raw Storm Events + GHCN-Daily .csv.gz
  3. scripts/ingest-noaa-storm-events.mjs     x4 (one per county)
  4. scripts/ingest-noaa-ghcn-daily.mjs       x4 (one per county)
  5. scripts/import_county_flood_data.py      flood-hazard-layers geometry --
                                               only if the sibling `Flood Project/`
                                               directory is present; see below
  6. pipeline/build_county_collections_geopackage.py

Step 5 is the one piece this cannot fully self-serve: the hazard-layer GeoJSON
has no public, scripted source, only the sibling `Flood Project/` working
directory. If that directory isn't next to this repo, step 5 is skipped with a
warning and the GeoPackage still builds -- just without flood-hazard-layers
content for counties that don't already have it on disk from a previous run.

Run:  uv run --group pipeline python pipeline/build_all.py
Safe to re-run: every step it calls is independently idempotent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Same default + override as SRC_RAW in scripts/import_county_flood_data.py.
FLOOD_PROJECT_DIR = Path(
    os.environ.get(
        "RGV_FLOOD_PROJECT_RAW_DIR",
        "C:/Users/danny/Documents/Code Projects/Flood Project/data/raw",
    )
)
NOAA_RAW_DIR = REPO_ROOT / "tmp" / "noaa"

COUNTY_CZ_NAMES = {
    "cameron": "CAMERON",
    "hidalgo": "HIDALGO",
    "starr": "STARR",
    "willacy": "WILLACY",
}


def run(*args: str) -> None:
    print("$", " ".join(args))
    subprocess.run(args, check=True, cwd=REPO_ROOT)


def run_python(script: str, *args: str) -> None:
    run(sys.executable, script, *args)


def main() -> None:
    print("== 1/6 scaffold county collections ==")
    run_python("scripts/scaffold_county_collections.py")

    print("\n== 2/6 download raw NOAA files ==")
    run("node", "scripts/download-noaa-source-files.mjs", str(NOAA_RAW_DIR.relative_to(REPO_ROOT)))

    print("\n== 3/6 + 4/6 ingest NOAA records, per county ==")
    for slug, cz_name in COUNTY_CZ_NAMES.items():
        run(
            "node",
            "scripts/ingest-noaa-storm-events.mjs",
            str(NOAA_RAW_DIR / "storm-events"),
            f"data/{slug}-county/records/events-and-public-reports/noaa-storm-events.ndjson",
            f"data/{slug}-county/sources/official-events/noaa-storm-events-2000-2025.json",
            cz_name,
        )
        run(
            "node",
            "scripts/ingest-noaa-ghcn-daily.mjs",
            str(NOAA_RAW_DIR / f"ghcn-{slug}"),
            f"data/{slug}-county/records/layers-and-weather/noaa-ghcn-daily-2000-2025.ndjson",
            f"data/{slug}-county/sources/weather/noaa-ghcn-daily-2000-2025.json",
            slug,
        )

    print("\n== 5/6 import flood-hazard-layers geometry ==")
    if FLOOD_PROJECT_DIR.is_dir():
        run_python("scripts/import_county_flood_data.py")
    else:
        print(
            f"[skip] {FLOOD_PROJECT_DIR} not found -- flood-hazard-layers/*.geojson "
            "will not be (re)created here.\n"
            "       See README 'Raw per-county data' for how to get it."
        )

    print("\n== 6/6 build the GeoPackage ==")
    run_python("pipeline/build_county_collections_geopackage.py")

    print("\nDone: data/generated/county-collections.gpkg is up to date.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"step failed ({error.returncode}): {' '.join(error.cmd)}") from error


