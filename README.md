# RGV Flood Impact Visualizer

CSCI 4390 Senior Project — Danny McClain, Luis Garcia. Faculty adviser: Sergei Chuprov.

A browser map that compares **best-available flood-hazard information** across the
four Lower Rio Grande Valley counties — **Cameron, Hidalgo, Starr, Willacy** — with
a browsable history of documented flood events, rainfall records, local news and
government reports, and an address search.

> Educational and comparative only. Not for flood-insurance, emergency-routing, or
> engineering decisions. It does not compute flood depth, predict active flooding,
> or certify a property's flood zone. Historical reports are not live conditions.

## Stack

- **Backend:** Flask + `jinja-partials`
- **Frontend:** server-rendered HTML, HTMX for the side panels, Leaflet for the map
- **Pipeline:** Python (`geopandas` / `shapely` / `pyproj`) for the spatial prep;
  the event/report/rainfall builder is standard-library only
- **Runtime external call:** the header address search geocodes through
  OpenStreetMap Nominatim, client-side from the browser. Everything else the app
  serves is precomputed by the pipeline — the server makes no outbound requests.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.13+, it manages the venv)
- Node 18+ — **only** to re-run the NOAA ingest scripts in `scripts/*.mjs`; not
  needed for a normal run (their output is committed)

## Setup (after a fresh clone)

```bash
uv sync --group dev --group pipeline          # install everything

uv run --group pipeline python pipeline/build_layers.py   # hazard layers  (~90 s)
uv run python pipeline/build_events.py                    # events, reports, rainfall  (~1 s)

uv run flask --app rgv_flood run --debug      # http://127.0.0.1:5000
```

The generated files under `src/rgv_flood/static/data/` are gitignored, so the two
`build_*` steps are required after every clone. Without them the map loads but
shows no layers.

## Everyday commands

| Command | What it does |
| --- | --- |
| `uv run flask --app rgv_flood run --debug` | Dev server with autoreload at `:5000` |
| `uv run pytest` | Run the test suite |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Format |
| `uv run --group pipeline python pipeline/build_layers.py` | Rebuild the hazard-layer GeoJSON + `layers.json` |
| `uv run python pipeline/build_events.py` | Rebuild `flood-events.geojson`, `flood-reports.json`, `rainfall-records.json` |
| `uv run --group pipeline python pipeline/build_county_collections_geopackage.py` | Build the local query GeoPackage from all canonical county collections |

Rebuild after changing anything the pipeline reads (`data/**`), the severity rules
in `src/rgv_flood/severity.py`, or the pipeline scripts themselves.

### Local county-collections GeoPackage

The canonical files in `data/<county>-county/` remain the source of record. To
produce a deterministic local relational/spatial database from all four
collections, run:

```bash
uv run --group pipeline python pipeline/build_county_collections_geopackage.py
```

It writes `data/generated/county-collections.gpkg`, which is ignored by Git. Use
`--output path/to/file.gpkg` to place the artifact elsewhere. The build validates
GeoJSON geometry and canonical record identities, stores usable geometry as native
EPSG:4326 GeoPackage geometry, and writes atomically: a failed build leaves an
existing output untouched. This artifact is a local developer query boundary; the
app continues to read its precomputed static data as before.

## Dependency groups

```bash
uv sync                       # app only (Flask + jinja-partials)
uv sync --group dev           # + pytest, ruff
uv sync --group pipeline      # + geopandas, shapely, pyproj, requests, beautifulsoup4
```

`--group pipeline` is only needed to run `pipeline/build_layers.py`. The app,
`build_events.py`, and the tests do not use it.

## One-off / data-acquisition scripts

Not part of the normal workflow. The output of all of these is already committed —
run them only to re-acquire or extend the source data. No `uv` deps; the `.mjs`
scripts are plain Node with no packages.

| Script | Purpose |
| --- | --- |
| `scripts/ingest-noaa-storm-events.mjs` | NOAA Storm Events → flood-event NDJSON |
| `scripts/ingest-noaa-ghcn-daily.mjs` | NOAA GHCN-Daily → weather-observation NDJSON |
| `scripts/import_county_flood_data.py` | Copies processed hazard GeoJSON in from the sibling `Flood Project/` dir, split per county |
| `scripts/scaffold_county_collections.py` | Regenerates the `data/<county>-county/` folder scaffold |

```bash
uv run python scripts/import_county_flood_data.py       # needs ../Flood Project/
uv run python scripts/scaffold_county_collections.py
```

### Re-ingesting the NOAA records (Node)

Both `.mjs` scripts take a directory of downloaded `.csv.gz` files and write an
NDJSON file plus a JSON source note:

```
node scripts/<script>.mjs  <gzip-directory>  <output.ndjson>  <source-note.json>
```

**Storm events** — download every annual detail file for 2000–2025 from
<https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/>
(`StormEvents_details-ftp_v1.0_d{YEAR}_c*.csv.gz`) into one folder, then:

```bash
node scripts/ingest-noaa-storm-events.mjs \
  ./tmp/storm-events \
  data/hidalgo-county/records/events-and-public-reports/noaa-storm-events.ndjson \
  data/hidalgo-county/sources/official-events/noaa-storm-events-2000-2025.json
```

It filters to `STATE=TEXAS`, `CZ_NAME=HIDALGO`, and flood-type events. The public
news / government reports in that NDJSON were added by hand, not by the script.

**GHCN-Daily weather** — download these 9 station files from
<https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station/> into one folder:
`USW00012959 USW00012987 USC00412758 USC00414139 USC00415701 USC00415836
USC00415972 USC00415973 USC00419588` (`.csv.gz` each), then:

```bash
node scripts/ingest-noaa-ghcn-daily.mjs \
  ./tmp/ghcn \
  data/hidalgo-county/records/layers-and-weather/noaa-ghcn-daily-2000-2025.ndjson \
  data/hidalgo-county/sources/weather/noaa-ghcn-daily-2000-2025.json
```

It keeps PRCP / TMAX / TMIN / AWND for 2000-01-01 through 2025-12-31 and drops
rows with a nonblank NOAA quality flag.

After re-ingesting, rebuild the overlays: `uv run python pipeline/build_events.py`.

## Data sources

| Layer | Source | Coverage |
| --- | --- | --- |
| Flood hazard zones | FEMA National Flood Hazard Layer (NFHL) | Cameron, Starr, Willacy |
| Flood hazard zones | Hidalgo County Drainage District No. 1 digitized 1981 FIRM (no FEMA digital data) | Hidalgo |
| Modeled flood extent | TWDB 2025 cursory floodplain dataset (Fathom 3 m) — contextual, not regulatory | all four |
| County boundaries | US Census TIGER/Line 2023 | all four |
| Flood events + weather | NOAA NCEI Storm Events + GHCN-Daily, 2000–2025 | Hidalgo only (so far) |
| Local reports | Hidalgo County / City of McAllen / KRGV, tied to documented events | Hidalgo only |

## Layout

```
src/rgv_flood/
  __init__.py         app factory
  config.py           paths + map defaults (override via RGV_* env vars)
  severity.py         the ONLY place source categories become a relative class
  views/map.py        routes: page, /api/layers, /api/flood-events, /partials/*
  data_access.py      read-only access to the pipeline outputs
  templates/          index.html + partials/ (metadata, events, rainfall, reports)
  static/
    js/map.js         Leaflet setup, layer toggles, event layer, address search
    css/app.css
    data/             pipeline outputs the app serves as-is (mostly gitignored)
pipeline/
  build_layers.py     hazard layers  -> static/data/*.geojson + layers.json
  build_events.py     NOAA records   -> flood-events / flood-reports / rainfall
data/
  <county>-county/    per-county collection: manifest, schemas, sources, records,
                      flood-hazard-layers/  (see data/hidalgo-county/README.md)
scripts/              one-off ingest / import helpers (see above)
tests/
```

Config is overridable from the environment — e.g. `RGV_MAP_DATA_DIR` to point the
app at a different `static/data` directory (the test suite uses this).
