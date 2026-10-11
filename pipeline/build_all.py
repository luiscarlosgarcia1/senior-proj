#!/usr/bin/env python3
"""One command builds the central database, `data/generated/rgv-flood.sqlite3`.

Every source is pulled into memory and written straight to the database; no
data files are generated along the way. Steps, in order:

  1. build_events.py   flood events, local reports, weather stations and their
                       daily readings (NOAA Storm Events and GHCN-Daily, plus the
                       curated reports in data/seed/)
  2. build_layers.py   every map layer (seed GeoJSON in data/seed/, Overture
                       bridges and dams, the Hidalgo drainage district's layers,
                       FEMA insurance claims by census tract)

The publishers' own files are kept in the gitignored `tmp/` download cache, so a
rebuild only fetches what is missing; delete that folder to download everything
fresh. `data/seed/` holds the few inputs that cannot be downloaded.

Run:  uv run --group pipeline python pipeline/build_all.py
Safe to re-run: each step replaces only its own tables, in one transaction.
"""

from __future__ import annotations

import subprocess
import sys

from paths import DATABASE, REPO_ROOT

STEPS = [
    ("flood events, reports and weather", "pipeline/build_events.py"),
    ("map layers", "pipeline/build_layers.py"),
]


def main() -> None:
    for number, (title, script) in enumerate(STEPS, start=1):
        # Flushed so each heading lands above its step's own output.
        print(f"\n== {number}/{len(STEPS)} {title} ==\n$ python {script}", flush=True)
        subprocess.run([sys.executable, script], check=True, cwd=REPO_ROOT)
    print(f"\nDone: {DATABASE.relative_to(REPO_ROOT)} is up to date.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"step failed ({error.returncode}): {' '.join(error.cmd)}") from error
