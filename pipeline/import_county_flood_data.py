#!/usr/bin/env python3
"""One-off import: pull the already-downloaded official flood-hazard layers from
the earlier "Flood Project" working directory into this repo, split per county.

This does NOT re-download anything and does NOT touch the Flask app or the NOAA
ingest scripts. It only reads GeoJSON from the sibling project and writes a
`flood-hazard-layers/` folder under each `data/<county>-county/`.

Source project (read-only): `paths.FLOOD_PROJECT_RAW`, overridable with the
RGV_FLOOD_PROJECT_RAW_DIR environment variable.

Layers per county:
    boundary.geojson              US Census TIGER 2023 county polygon
    fema-nfhl.geojson             FEMA National Flood Hazard Layer (Cameron/Starr/Willacy only)
    hcdd1-firm-1981.geojson       Hidalgo Co. Drainage District No. 1 digitized 1981 FIRM (Hidalgo only)
    twdb-cursory-1in100.geojson   TWDB Fathom modeled extent, 1% annual chance (contextual, not official)
    twdb-cursory-1in500.geojson   TWDB Fathom modeled extent, 0.2% annual chance (contextual, not official)

Run:  uv run python pipeline/import_county_flood_data.py
Safe to re-run (overwrites the imported files; leaves everything else alone).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonio import feature_collection, write_json
from paths import FLOOD_PROJECT_RAW as SRC_RAW
from paths import hazard_layers_dir

from rgv_flood.counties import COUNTIES, NFHL_COUNTIES, SHORT_NAMES

RETRIEVED_AT = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(name: str) -> dict:
    return json.loads((SRC_RAW / name).read_text(encoding="utf-8"))


def _write_features(path: Path, features: list[dict]) -> int:
    path.write_text(json.dumps(feature_collection(features)), encoding="utf-8")
    return len(features)


def _layer(file: str, *, title: str, publisher: str, dataset: str, status: str, vintage: str, crs: str,
           count: int, note: str) -> dict:
    """One entry in a county's flood-hazard-layers manifest."""
    return {
        "id": file.removesuffix(".geojson"),
        "file": file,
        "title": title,
        "source_publisher": publisher,
        "source_dataset": dataset,
        "status": status,
        "vintage": vintage,
        "crs": crs,
        "feature_count": count,
        "note": note,
    }


def _county_layers(slug: str, out_dir: Path, sources: dict) -> list[dict]:
    """Write one county's GeoJSON files and return their manifest entries."""
    name, geoid = SHORT_NAMES[slug], COUNTIES[slug]["fips"]

    boundary = [f for f in sources["counties"]["features"] if f["properties"].get("GEOID") == geoid]
    layers = [_layer(
        "boundary.geojson",
        title=f"{name} County boundary",
        publisher="U.S. Census Bureau",
        dataset="TIGER/Line 2023 — Counties",
        status="reference",
        vintage="2023",
        crs="EPSG:4269",
        count=_write_features(out_dir / "boundary.geojson", boundary),
        note="Study-area boundary only. Not flood evidence.",
    )]

    if slug in NFHL_COUNTIES:
        nfhl = _load(f"nfhl_{slug}.geojson")["features"]
        layers.append(_layer(
            "fema-nfhl.geojson",
            title=f"FEMA National Flood Hazard Layer — {name} County",
            publisher="Federal Emergency Management Agency",
            dataset="National Flood Hazard Layer, MapServer layer 28 (Flood Hazard Zones)",
            status="official_effective",
            vintage="effective FIRM date varies by panel",
            crs="EPSG:4326",
            count=_write_features(out_dir / "fema-nfhl.geojson", nfhl),
            note=(
                "Downloaded by bounding-box query; a few polygons from neighboring "
                "counties may spill in and should be clipped to the boundary before use. "
                "Not a property-level determination."
            ),
        ))
    else:
        firm = _load("hidalgo_firm_hcdd1.geojson")["features"]
        layers.append(_layer(
            "hcdd1-firm-1981.geojson",
            title="Hidalgo County digitized 1981 FIRM",
            publisher="Hidalgo County Drainage District No. 1",
            dataset="FloodMapService/FeatureServer/0 (HidalgoFIRM), digitized copy of the 1981 FIRM",
            status="legacy_local_reference",
            vintage="1981 base map; some zones revised by later LOMR",
            crs="EPSG:4326",
            count=_write_features(out_dir / "hcdd1-firm-1981.geojson", firm),
            note=(
                "The only flood-zone dataset that exists for Hidalgo County — FEMA has no "
                "digital NFHL coverage here. 44 years old; urban core largely undrawn. "
                "Zone semantics not confirmed equivalent to current FEMA classes."
            ),
        ))

    for freq, chance in (("1in100", "1% annual chance"), ("1in500", "0.2% annual chance")):
        county_features = [f for f in sources[freq]["features"] if f.get("properties", {}).get("county") == name]
        file = f"twdb-cursory-{freq}.geojson"
        layers.append(_layer(
            file,
            title=f"TWDB modeled flood extent — {chance} — {name} County",
            publisher="Texas Water Development Board",
            dataset="2025 Cursory Floodplain Dataset (Fathom 3m), Region 15, clipped to county",
            status="modeled_contextual",
            vintage="2025",
            crs="EPSG:4326",
            count=_write_features(out_dir / file, county_features),
            note="Modeled estimate, NOT an effective FEMA map or regulatory determination.",
        ))
    return layers


def main() -> None:
    if not SRC_RAW.is_dir():
        raise SystemExit(f"source not found: {SRC_RAW}")

    sources = {
        "counties": _load("rgv_counties.geojson"),
        "1in100": _load("twdb_cursory_1in100_rgv.geojson"),
        "1in500": _load("twdb_cursory_1in500_rgv.geojson"),
    }
    for slug, county in COUNTIES.items():
        out_dir = hazard_layers_dir(slug)
        out_dir.mkdir(parents=True, exist_ok=True)
        layers = _county_layers(slug, out_dir, sources)

        manifest = {
            "county": SHORT_NAMES[slug],
            "county_slug": slug,
            "geoid": county["fips"],
            "imported_from": str(SRC_RAW),
            "imported_at": RETRIEVED_AT,
            "importer": "pipeline/import_county_flood_data.py",
            "layers": layers,
        }
        write_json(out_dir / "manifest.json", manifest)
        (out_dir / "README.md").write_text(_readme(SHORT_NAMES[slug], layers), encoding="utf-8")
        print(f"[{slug}] {len(layers)} layers, {sum(l['feature_count'] for l in layers)} features -> {out_dir}")


def _readme(name: str, layers: list[dict]) -> str:
    rows = "\n".join(
        f"| `{layer['file']}` | {layer['source_publisher']} | {layer['status']} | "
        f"{layer['feature_count']} | {layer['vintage']} |"
        for layer in layers
    )
    return f"""# {name} County — flood-hazard layers

Official and contextual flood-hazard geometry for {name} County, imported from the
earlier *Flood Project* working directory (already downloaded and processed there).
Generated by `pipeline/import_county_flood_data.py` — do not hand-edit; re-run the
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
