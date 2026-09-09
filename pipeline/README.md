# Preprocessing pipeline

Offline data engineering. Turns the collected source data under `data/` into the
small files the Flask app serves from `src/rgv_flood/static/data/`. Not shipped
with the app.

Everything here is deterministic and re-runnable — it only overwrites its own
outputs. All generated files except `layers.json` are gitignored, so both scripts
must run after a clone.

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
| `layers.json` | manifest (id, file, title, description, source, vintage, limitation) — **tracked** |

Needs `OGR_GEOJSON_MAX_OBJ_SIZE=0` (the script sets it) — a few FEMA polygons
exceed GDAL's default per-feature size cap.

## `build_events.py` — events, reports, rainfall

```bash
uv run python pipeline/build_events.py                       # ~1 s, stdlib only
```

Reads the schema-validated NDJSON under `data/hidalgo-county/records/` (NOAA Storm
Events + GHCN-Daily, collected via `scripts/*.mjs`).

| Output | Contents |
| --- | --- |
| `flood-events.geojson` | Documented flood events as points; events whose source coordinate falls outside Hidalgo County are kept but not mapped (`geometry_note`) |
| `flood-reports.json` | The 16 local-news / government reports tied to those events |
| `rainfall-records.json` | The 15 wettest single gauge-days, 2000–2025 |

## Conventions

- Reproject everything to EPSG:4326.
- Simplify geometry only where visual meaning is retained.
- Every hazard feature keeps `source`, `original_category`, and `relative_class`.
- Never invent a coordinate. NOAA rows with an obviously wrong `BEGIN_LON/LAT`
  keep the record and drop the point rather than guessing a location.
