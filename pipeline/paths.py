"""Where everything lives: the one place the repo's data layout is spelled out."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

# The central database: everything the build produces and everything the app reads.
DATABASE = DATA_DIR / "generated" / "rgv-flood.sqlite3"

# The only data files in the repository: source geometry and curated records
# that no publisher offers as a scripted download (see data/seed/README.md).
SEED_DIR = DATA_DIR / "seed"

# Publishers' own files, kept exactly as downloaded so a rebuild doesn't fetch
# them again. Only a cache: delete it and the next build downloads everything.
DOWNLOAD_CACHE = REPO_ROOT / "tmp"

ML_RAW = DATA_DIR / "ml" / "raw"  # inputs for the Hidalgo model (fetch_ml_inputs.py)


def seed_file(slug: str, name: str, seed_dir: Path = SEED_DIR) -> Path:
    """One county's seed file, e.g. seed_file("starr", "fema-nfhl.geojson")."""
    return seed_dir / slug / name


def county_boundary(slug: str, seed_dir: Path = SEED_DIR) -> dict:
    """The county's Census TIGER boundary as a GeoJSON geometry."""
    path = seed_file(slug, "boundary.geojson", seed_dir)
    return json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"]
