#!/usr/bin/env python3
"""One-off import: pull the already-downloaded official flood-hazard layers from
the earlier "Flood Project" working directory into this repo, split per county.

This does NOT re-download anything and does NOT touch the Flask app or the NOAA
ingest scripts. It only reads GeoJSON from the sibling project and writes a
`flood-hazard-layers/` folder under each `data/<county>-county/`.

Source project (read-only), overridable with RGV_FLOOD_PROJECT_RAW_DIR:
    C:/Users/danny/Documents/Code Projects/Flood Project/data/raw/

Layers per county:
    boundary.geojson              US Census TIGER 2023 county polygon
    fema-nfhl.geojson             FEMA National Flood Hazard Layer (Cameron/Starr/Willacy only)
    hcdd1-firm-1981.geojson       Hidalgo Co. Drainage District No. 1 digitized 1981 FIRM (Hidalgo only)
    twdb-cursory-1in100.geojson   TWDB Fathom modeled extent, 1% annual chance (contextual, not official)
    twdb-cursory-1in500.geojson   TWDB Fathom modeled extent, 0.2% annual chance (contextual, not official)

Run:  uv run python scripts/import_county_flood_data.py
Safe to re-run (overwrites the imported files; leaves everything else alone).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_RAW = Path(
    os.environ.get(
        "RGV_FLOOD_PROJECT_RAW_DIR",
        "C:/Users/danny/Documents/Code Projects/Flood Project/data/raw",
    )
).resolve()
DATA_DIR = REPO_ROOT / "data"

# slug -> (TIGER NAME, TIGER GEOID)
COUNTIES = {
    "cameron": ("Cameron", "48061"),
    "hidalgo": ("Hidalgo", "48215"),
    "starr": ("Starr", "48427"),
    "willacy": ("Willacy", "48489"),
}

# FEMA NFHL has real digital coverage only for these three.
NFHL_COUNTIES = {"cameron", "starr", "willacy"}

RETRIEVED_AT = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(name: str) -> dict:
    return json.loads((SRC_RAW / name).read_text(encoding="utf-8"))


def _write_fc(path: Path, features: list[dict], extra: dict | None = None) -> int:
    fc = {"type": "FeatureCollection", "features": features}
    if extra:
        fc.update(extra)
    path.write_text(json.dumps(fc), encoding="utf-8")
    return len(features)


def _split_by_county(fc: dict, name: str) -> list[dict]:
    return [f for f in fc["features"] if f.get("properties", {}).get("county") == name]


def main() -> None:
    if not SRC_RAW.is_dir():
        raise SystemExit(f"source not found: {SRC_RAW}")

    counties_fc = _load("rgv_counties.geojson")
    twdb_100 = _load("twdb_cursory_1in100_rgv.geojson")
    twdb_500 = _load("twdb_cursory_1in500_rgv.geojson")

    for slug, (name, geoid) in COUNTIES.items():
        out_dir = DATA_DIR / f"{slug}-county" / "flood-hazard-layers"
        out_dir.mkdir(parents=True, exist_ok=True)

        layers: list[dict] = []

        # 1. county boundary (single feature)
        boundary = [f for f in counties_fc["features"] if f["properties"].get("GEOID") == geoid]
        n = _write_fc(out_dir / "boundary.geojson", boundary)
        layers.append({
            "id": "boundary",
            "file": "boundary.geojson",
            "title": f"{name} County boundary",
            "source_publisher": "U.S. Census Bureau",
            "source_dataset": "TIGER/Line 2023 — Counties",
            "status": "reference",
            "vintage": "2023",
            "crs": "EPSG:4269",
            "feature_count": n,
            "note": "Study-area boundary only. Not flood evidence.",
        })

        # 2. FEMA NFHL (three counties) or HCDD1 FIRM (Hidalgo)
        if slug in NFHL_COUNTIES:
            nfhl = _load(f"nfhl_{slug}.geojson")
            n = _write_fc(out_dir / "fema-nfhl.geojson", nfhl["features"])
            layers.append({
                "id": "fema-nfhl",
                "file": "fema-nfhl.geojson",
                "title": f"FEMA National Flood Hazard Layer — {name} County",
                "source_publisher": "Federal Emergency Management Agency",
                "source_dataset": "National Flood Hazard Layer, MapServer layer 28 (Flood Hazard Zones)",
                "status": "official_effective",
                "vintage": "effective FIRM date varies by panel",
                "crs": "EPSG:4326",
                "feature_count": n,
                "note": (
                    "Downloaded by bounding-box query; a few polygons from neighboring "
                    "counties may spill in and should be clipped to the boundary before use. "
                    "Not a property-level determination."
                ),
            })
        else:  # hidalgo
            firm = _load("hidalgo_firm_hcdd1.geojson")
            n = _write_fc(out_dir / "hcdd1-firm-1981.geojson", firm["features"])
            layers.append({
                "id": "hcdd1-firm-1981",
                "file": "hcdd1-firm-1981.geojson",
                "title": "Hidalgo County digitized 1981 FIRM",
                "source_publisher": "Hidalgo County Drainage District No. 1",
                "source_dataset": "FloodMapService/FeatureServer/0 (HidalgoFIRM), digitized copy of the 1981 FIRM",
                "status": "legacy_local_reference",
                "vintage": "1981 base map; some zones revised by later LOMR",
                "crs": "EPSG:4326",
                "feature_count": n,
                "note": (
                    "The only flood-zone dataset that exists for Hidalgo County — FEMA has no "
                    "digital NFHL coverage here. 44 years old; urban core largely undrawn. "
                    "Zone semantics not confirmed equivalent to current FEMA classes."
                ),
            })

        # 3. TWDB modeled extent, both frequencies
        for freq, fc, chance in (
            ("1in100", twdb_100, "1% annual chance"),
            ("1in500", twdb_500, "0.2% annual chance"),
        ):
            feats = _split_by_county(fc, name)
            fname = f"twdb-cursory-{freq}.geojson"
            n = _write_fc(out_dir / fname, feats)
            layers.append({
                "id": f"twdb-cursory-{freq}",
                "file": fname,
                "title": f"TWDB modeled flood extent — {chance} — {name} County",
                "source_publisher": "Texas Water Development Board",
                "source_dataset": "2025 Cursory Floodplain Dataset (Fathom 3m), Region 15, clipped to county",
                "status": "modeled_contextual",
                "vintage": "2025",
                "crs": "EPSG:4326",
                "feature_count": n,
                "note": "Modeled estimate, NOT an effective FEMA map or regulatory determination.",
            })

        manifest = {
            "county": name,
            "county_slug": slug,
            "geoid": geoid,
            "imported_from": str(SRC_RAW),
            "imported_at": RETRIEVED_AT,
            "importer": "scripts/import_county_flood_data.py",
            "layers": layers,
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (out_dir / "README.md").write_text(_readme(name, slug, layers), encoding="utf-8")

        total = sum(layer["feature_count"] for layer in layers)
        print(f"[{slug}] {len(layers)} layers, {total} features -> {out_dir}")


def _readme(name: str, slug: str, layers: list[dict]) -> str:
    rows = "\n".join(
        f"| `{layer['file']}` | {layer['source_publisher']} | {layer['status']} | "
        f"{layer['feature_count']} | {layer['vintage']} |"
        for layer in layers
    )
    return f"""# {name} County — flood-hazard layers

Official and contextual flood-hazard geometry for {name} County, imported from the
earlier *Flood Project* working directory (already downloaded and processed there).
Generated by `scripts/import_county_flood_data.py` — do not hand-edit; re-run the
importer instead.

| File | Publisher | Status | Features | Vintage |
| --- | --- | --- | --- | --- |
{rows}

**Status meanings**

- `official_effective` — FEMA NFHL, the effective regulatory flood hazard layer.
- `legacy_local_reference` — Hidalgo's digitized 1981 FIRM; no FEMA digital equivalent exists.
- `modeled_contextual` — TWDB Fathom modeled extent; **not** a regulatory determination.
- `reference` — study-area boundary only.

All layers are EPSG:4326 except `boundary.geojson` (EPSG:4269, as delivered by TIGER).
See `manifest.json` for full provenance per layer.
"""


if __name__ == "__main__":
    main()
