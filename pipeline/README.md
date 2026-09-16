# Preprocessing pipeline

Offline data engineering. Turns the collected source data under `data/` into the
small files the Flask app serves from `src/rgv_flood/static/data/`. Not shipped
with the app.

Everything here is deterministic and re-runnable — it only overwrites its own
outputs. Every generated file, including `layers.json`, is gitignored, so both
scripts must run after a clone before the app has anything to serve.

`schemas/` in this directory is the one exception to "gitignored build output"
in the whole `data/`-adjacent tree — it's the tracked template
`scripts/scaffold_county_collections.py` copies into every county's own
(gitignored) `schemas/`. Nothing generates these two files; they're hand-authored
validation contracts, edit them directly if the record shape changes.

## `build_all.py` — the whole thing, one command

```bash
uv run --group pipeline python pipeline/build_all.py
```

Runs every step below in order, for all four counties, from a bare clone:
scaffold the county folders, download the raw NOAA files, ingest them, import
the flood-hazard-layer GeoJSON (skipped with a warning if the sibling
`Flood Project/` directory isn't found), then build the GeoPackage. See its
docstring for the exact step list and how to run just one of them.

## `build_county_collections_geopackage.py` — local spatial query database

```bash
uv run --group pipeline python pipeline/build_county_collections_geopackage.py
```

Builds the ignored `data/generated/county-collections.gpkg` from the four
canonical county collections in fixed Cameron, Hidalgo, Starr, Willacy order.
Pass `--output path/to/file.gpkg` to override that destination. It records exact
SHA-256 fingerprints for every canonical input artifact, links records and layers
to their source artifacts, retains source JSON and nullable-geometry evidence, and
stores usable GeoJSON as native EPSG:4326 GeoPackage geometry. It validates input
and replaces the destination atomically, so malformed geometry or duplicate record
identities never produce a partial artifact. It is deliberately separate from the
app's static-overlay builders.

## `build_layers.py` — hazard layers

```bash
uv run --group pipeline python pipeline/build_layers.py      # ~90 s
```

Reads `data/<county>-county/flood-hazard-layers/*.geojson` (imported from the
earlier *Flood Project* working dir) and for each output layer: reprojects to
EPSG:4326, clips FEMA NFHL to the true county boundary, assigns `relative_class`
from `rgv_flood.severity`, dissolves adjacent same-class polygons, and simplifies
geometry.

| Output | From |
| --- | --- |
| `county-boundaries.geojson` | TIGER county polygons, all four counties |
| `fema-nfhl.geojson` | FEMA NFHL — Cameron, Starr, Willacy |
| `hidalgo-firm-1981.geojson` | Hidalgo County DD No. 1 digitized 1981 FIRM |
| `twdb-cursory-1in100.geojson` / `-1in500.geojson` | TWDB 2025 cursory floodplain, all four |
| `layers.json` | manifest (id, file, title, description, source, vintage, limitation) |

Needs `OGR_GEOJSON_MAX_OBJ_SIZE=0` (the script sets it) — a few FEMA polygons
exceed GDAL's default per-feature size cap.

## `build_events.py` — events, reports, rainfall

```bash
uv run python pipeline/build_events.py                       # ~1 s, stdlib only
```

Reads the schema-validated NDJSON under `data/<county>-county/records/` for all
four counties (NOAA Storm Events + GHCN-Daily, collected via `scripts/*.mjs`)
and merges them, each event/report/day tagged with its own `county`.

| Output | Contents |
| --- | --- |
| `flood-events.geojson` | Documented flood events as points, all four counties; an event whose source coordinate falls outside its own county's boundary is kept but not mapped (`geometry_note`) |
| `flood-reports.json` | Local-news / government reports tied to those events — 16 so far, **Hidalgo only**; the other three counties have none because nobody's done that hand-curation pass for them yet, not because no script exists |
| `rainfall-records.json` | The 15 wettest single gauge-days on record, ranked across every county's stations |

## Conventions

- Reproject everything to EPSG:4326.
- Simplify geometry only where visual meaning is retained.
- Every hazard feature keeps `source`, `original_category`, and `relative_class`.
- Never invent a coordinate. NOAA rows with an obviously wrong `BEGIN_LON/LAT`
  keep the record and drop the point rather than guessing a location.
