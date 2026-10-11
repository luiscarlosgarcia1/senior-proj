#!/usr/bin/env python3
"""One command, start to finish: gather each county's source data, then build
the two databases made from it.

  data/generated/rgv-flood.sqlite3         the app database: every map layer,
                                           flood event, report and rainfall
                                           record the Flask app serves
  data/generated/county-collections.gpkg   a queryable archive of the full
                                           county collections (not read by the app)

Most of `data/<county>-county/` is gitignored build output; on a bare clone this
is the script that produces it. Steps, in order:

  1. scaffold_county_collections.py           manifest, schemas, folder skeleton
  2. noaa_ingest.py                           download + ingest NOAA Storm Events
                                              and GHCN-Daily for all four counties
  3. import_county_flood_data.py              flood-hazard-layers geometry -- only
                                              if the sibling `Flood Project/`
                                              directory is present; see below
  4. import_overture_infrastructure.py        bridges + dams, public source
  5. build_layers.py                          app database: map layers
  6. build_events.py                          app database: events, reports, rainfall
  7. build_county_collections_geopackage.py   the archive GeoPackage

Step 3 is the one piece this cannot fully self-serve: the hazard-layer GeoJSON
has no public, scripted source, only the sibling `Flood Project/` working
directory. If that directory isn't next to this repo, the step is skipped with a
warning and everything still builds from the layers already tracked in git.
Step 4 needs nothing from Flood Project (Overture Maps is public), so it always
runs, using each county's boundary.geojson to keep results to the four counties
and out of Mexico. Step 5 adds the drainage-district and insurance-claims layers
only if `fetch_ml_inputs.py` has downloaded their inputs.

Run:  uv run --group pipeline python pipeline/build_all.py
Safe to re-run: every step it calls is independently idempotent.
"""

from __future__ import annotations

import subprocess
import sys

from paths import APP_DB, FLOOD_PROJECT_RAW, GEOPACKAGE, REPO_ROOT


def run_python(script: str) -> None:
    print("$ python", script, flush=True)  # flushed so it lands above the step's own output
    subprocess.run([sys.executable, script], check=True, cwd=REPO_ROOT)


def main() -> None:
    steps = [
        ("scaffold county collections", "pipeline/scaffold_county_collections.py"),
        ("download and ingest NOAA records", "pipeline/noaa_ingest.py"),
        ("import flood-hazard-layers geometry", "pipeline/import_county_flood_data.py"),
        ("import Overture bridges + dams", "pipeline/import_overture_infrastructure.py"),
        ("app database: map layers", "pipeline/build_layers.py"),
        ("app database: events, reports, rainfall", "pipeline/build_events.py"),
        ("build the archive GeoPackage", "pipeline/build_county_collections_geopackage.py"),
    ]
    for number, (title, script) in enumerate(steps, start=1):
        print(f"\n== {number}/{len(steps)} {title} ==")
        if script.endswith("import_county_flood_data.py") and not FLOOD_PROJECT_RAW.is_dir():
            print(
                f"[skip] {FLOOD_PROJECT_RAW} not found -- flood-hazard-layers/*.geojson "
                "will not be (re)created here; the copies tracked in git are used."
            )
            continue
        run_python(script)

    print(f"\nDone: {APP_DB.relative_to(REPO_ROOT)} and {GEOPACKAGE.relative_to(REPO_ROOT)} are up to date.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"step failed ({error.returncode}): {' '.join(error.cmd)}") from error
