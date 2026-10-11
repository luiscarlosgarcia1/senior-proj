# Preprocessing pipeline

Offline data engineering. Turns the collected source data under `data/` into the
small files the Flask app serves from `src/rgv_flood/static/data/`. Not shipped
with the app.

Everything here is deterministic and re-runnable — it only overwrites its own
outputs. Every generated file, including `layers.json`, is gitignored, so
`build_layers.py` and `build_events.py` must run after a clone before the app has
anything to serve.

`schemas/` in this directory is the one exception to "gitignored build output"
in the whole `data/`-adjacent tree — it's the tracked template
`pipeline/scaffold_county_collections.py` copies into every county's own
(gitignored) `schemas/`. Nothing generates these two files; they're hand-authored
validation contracts, edit them directly if the record shape changes.

## `build_all.py` — the whole thing, one command

```bash
uv run --group pipeline python pipeline/build_all.py
```

Runs every step in order, for all four counties, from a bare clone: scaffold the
county folders, download and ingest the NOAA records (`noaa_ingest.py`), import the
flood-hazard-layer GeoJSON (skipped with a warning if the sibling `Flood Project/`
directory isn't found), import Overture bridges and dams, then build the
GeoPackage. See its docstring for the exact step list; each step is also a script
you can run on its own.

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
earlier *Flood Project* working dir) and for each hazard layer: reprojects to
EPSG:4326, clips FEMA NFHL to the true county boundary, assigns `relative_class`
from `rgv_flood.severity`, dissolves adjacent same-class polygons, and simplifies
geometry. Bridges and dams are kept as individual features (no severity, no
dissolve).

The code is split by concern: `build_layers.py` (hazard and infrastructure
builders, and the layer-id → builder table that drives `main()`),
`evidence_layers.py` (Hidalgo drainage-district and NFIP overlays),
`layer_meta.py` (descriptions, limitations and links to each publisher's own
map), and `layer_io.py` (the one function that writes a layer file).

| Output | From |
| --- | --- |
| `county-boundaries.geojson` | TIGER county polygons, all four counties |
| `fema-nfhl.geojson` | FEMA NFHL — Cameron, Starr, Willacy |
| `hidalgo-firm-1981.geojson` | Hidalgo County DD No. 1 digitized 1981 FIRM |
| `twdb-cursory-1in100.geojson` / `-1in500.geojson` | TWDB 2025 cursory floodplain, all four |
| `overture-bridges.geojson` / `overture-dams.geojson` | Overture Maps, clipped to the county polygons (`import_overture_infrastructure.py`) |
| `hcdd1-flood-extents`, `-flood-photos`, `-drainage`, `-bond-projects` | Hidalgo drainage district's published layers |
| `nfip-claims-by-tract.geojson` | FEMA NFIP claims per census tract |
| `layers.json` | manifest (id, file, title, description, source, vintage, limitation, links) |

The drainage-district and NFIP overlays need the raw downloads from
`fetch_ml_inputs.py` (`--only hcdd1,nfip,tracts`); without them those layers are
skipped and the rest still build.

Needs `OGR_GEOJSON_MAX_OBJ_SIZE=0` (the script sets it) — a few FEMA polygons
exceed GDAL's default per-feature size cap.

## `build_events.py` — events, reports, rainfall

```bash
uv run python pipeline/build_events.py                       # ~1 s
```

Reads the schema-validated NDJSON under `data/<county>-county/records/` for all
four counties (NOAA Storm Events + GHCN-Daily, collected via `pipeline/noaa_ingest.py`)
and merges them, each event/report/day tagged with its own `county`.

| Output | Contents |
| --- | --- |
| `flood-events.geojson` | Documented flood events as points, all four counties; an event whose source coordinate falls outside its own county's boundary is kept but not mapped (`geometry_note`) |
| `flood-reports.json` | Local-news / government reports tied to those events — 16 so far, **Hidalgo only**; the other three counties have none because nobody's done that hand-curation pass for them yet, not because no script exists |
| `rainfall-records.json` | The 15 wettest single gauge-days on record, ranked across every county's stations |

## `noaa_ingest.py` — NOAA Storm Events and GHCN-Daily

```bash
uv run python pipeline/noaa_ingest.py [download|ingest] [--county hidalgo]
```

Downloads NOAA's yearly Storm Events files and per-station GHCN-Daily files, then
writes each county's canonical NDJSON records and source notes. Storm Events files
are read once for all four counties. A county's hand-curated `public_report` rows
(Hidalgo's) are preserved across re-runs. Stations live in `noaa_stations.py`.

## `fetch_ml_inputs.py` — public inputs for the Hidalgo model

```bash
uv run --group pipeline python pipeline/fetch_ml_inputs.py [--only hcdd1,nfip,...]
```

Gathers elevation, NLCD, soils, rainfall-frequency grids, Overture layers, NFIP
claims and policies, and the drainage district's published layers into the
gitignored `data/ml/raw/`. Re-runs skip files already present. Shared HTTP helpers
(retries, resumable downloads) are in `net.py`.

## Shared helpers

Every script in this folder builds on the same four small modules, so a path, a
JSON format or an HTTP setting is defined in exactly one place:

| Module | What it holds |
| --- | --- |
| `paths.py` | Where things live: `data/`, each county's folders and record files, the app's `static/data/`, the live-signals database, the GeoPackage |
| `jsonio.py` | Reading NDJSON, writing readable JSON, canonical (sorted, compact) JSON, GeoJSON feature collections |
| `net.py` | HTTP GET for bytes, text and JSON, plus resumable downloads with retries |
| `rgv_flood.counties` | The four counties: slugs, FIPS codes, names, bounding box (shared with the Flask app) |

## Live signals

`run_nws.py`, `run_hidalgo_rss.py` and `run_drivetexas.py` each poll one official
source and store the result in `data/generated/live-signals.sqlite3` through
`live_signals.py` (`LiveSignalStore`). The Flask app runs all three on a timer;
each can also be run by hand, and takes `--output` to write somewhere else.
`run_live_signal_fixture.py` loads the test fixture instead of a live source.

## Conventions

- Reproject everything to EPSG:4326.
- Simplify geometry only where visual meaning is retained.
- Every hazard feature keeps `source`, `original_category`, and `relative_class`.
- Never invent a coordinate. NOAA rows with an obviously wrong `BEGIN_LON/LAT`
  keep the record and drop the point rather than guessing a location.
