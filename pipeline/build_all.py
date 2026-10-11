#!/usr/bin/env python3
"""One command, start to finish: scaffold the county collections, download and
ingest the NOAA source data for all four counties, import the flood-hazard and
infrastructure layers, and build the local query GeoPackage.

Most of `data/<county>-county/` is gitignored build output (see the repo README,
"Raw per-county data"); on a bare clone this is the script that produces it.
Steps, in order:

  1. scripts/scaffold_county_collections.py      manifest, schemas, folder skeleton
  2. pipeline/noaa_ingest.py                     download + ingest NOAA Storm Events
                                                  and GHCN-Daily for all four counties
  3. scripts/import_county_flood_data.py         flood-hazard-layers geometry --
                                                  only if the sibling `Flood Project/`
                                                  directory is present; see below
  4. scripts/import_overture_infrastructure.py   bridges + dams, public source
  5. pipeline/build_county_collections_geopackage.py

Step 3 is the one piece this cannot fully self-serve: the hazard-layer GeoJSON
has no public, scripted source, only the sibling `Flood Project/` working
directory. If that directory isn't next to this repo, the step is skipped with a
warning and the GeoPackage still builds from the layers already tracked in git.
Step 4 needs nothing from Flood Project (Overture Maps is public), so it always
runs, using each county's boundary.geojson to keep results to the four counties
and out of Mexico.

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


def run_python(script: str) -> None:
    print("$ python", script)
    subprocess.run([sys.executable, script], check=True, cwd=REPO_ROOT)


def main() -> None:
    steps = [
        ("scaffold county collections", "scripts/scaffold_county_collections.py"),
        ("download and ingest NOAA records", "pipeline/noaa_ingest.py"),
        ("import flood-hazard-layers geometry", "scripts/import_county_flood_data.py"),
        ("import Overture bridges + dams", "scripts/import_overture_infrastructure.py"),
        ("build the GeoPackage", "pipeline/build_county_collections_geopackage.py"),
    ]
    for number, (title, script) in enumerate(steps, start=1):
        print(f"\n== {number}/{len(steps)} {title} ==")
        if script.endswith("import_county_flood_data.py") and not FLOOD_PROJECT_DIR.is_dir():
            print(
                f"[skip] {FLOOD_PROJECT_DIR} not found -- flood-hazard-layers/*.geojson "
                "will not be (re)created here.\n"
                "       See README 'Raw per-county data' for how to get it."
            )
            continue
        run_python(script)

    print("\nDone: data/generated/county-collections.gpkg is up to date.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"step failed ({error.returncode}): {' '.join(error.cmd)}") from error
