# RGV Flood Impact Visualizer

CSCI 4390 Senior Project — Danny McClain, Luis Garcia. Faculty adviser: Sergei Chuprov.

A browser map that compares **best-available flood-hazard information** across the
four Lower Rio Grande Valley counties — **Cameron, Hidalgo, Starr, Willacy** — with
a browsable history of documented flood events, rainfall records, local news and
government reports, live National Weather Service alerts, and an address search.

> Educational and comparative only. Not for flood-insurance, emergency-routing, or
> engineering decisions. It does not compute flood depth, predict active flooding,
> or certify a property's flood zone. Historical reports are not live conditions;
> active weather alerts are live, but this is not a substitute for official
> emergency guidance.

## Stack

- **Backend:** Flask + `jinja-partials`
- **Frontend:** server-rendered HTML, HTMX for the side panels, Leaflet for the map
- **Pipeline:** Python (`geopandas` / `shapely` / `pyproj`) for the spatial prep;
  the event/report/rainfall builder is standard-library only
- **Runtime external calls, both client-side from the browser, no key needed:**
  the header address search geocodes through OpenStreetMap Nominatim, and the
  "Active weather alerts" panel polls `api.weather.gov/alerts/active` every
  5 minutes, filtered to the four counties by matching NWS's `areaDesc` text.
  Everything else the app serves is precomputed by the pipeline — the Flask
  server itself makes no outbound requests.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.13+, it manages the venv)
- Node 18+ — to run the NOAA ingest scripts in `scripts/*.mjs`. Their output
  (`data/<county>-county/records/`, `sources/`) is gitignored, so this is
  needed for a genuinely fresh setup, not just to "re-run" them

## Setup (after a fresh clone)

`data/` is entirely gitignored build output (see "Raw per-county data" below) —
on a fresh clone it's empty folders and nothing else. Populate it and build the
local database in one command:

```bash
uv sync --group dev --group pipeline                 # install everything

uv run --group pipeline python pipeline/build_all.py  # data/ -> county-collections.gpkg  (~2-3 min)
```

That runs, in order: scaffold the per-county folders → download the raw NOAA
files → ingest them for all four counties → import the flood-hazard-layer
GeoJSON (skipped with a warning if the sibling `Flood Project/` directory isn't
present — see below, it's the one piece with no public download) → build
`data/generated/county-collections.gpkg`. Every step is idempotent, so re-run
it any time; see `pipeline/build_all.py`'s docstring for the individual steps
if you want to run just one.

Then build what the *Flask app* serves (a separate, smaller pair of outputs
under `src/rgv_flood/static/data/`, also gitignored):

```bash
uv run --group pipeline python pipeline/build_layers.py   # hazard layers  (~90 s)
uv run python pipeline/build_events.py                    # events, reports, rainfall  (~1 s)

uv run flask --app rgv_flood run --debug                  # http://127.0.0.1:5000
```

Without those two, the map loads but shows no layers.

## Everyday commands

| Command | What it does |
| --- | --- |
| `uv run flask --app rgv_flood run --debug` | Dev server with autoreload at `:5000` |
| `uv run pytest` | Run the test suite |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Format |
| `uv run --group pipeline python pipeline/build_layers.py` | Rebuild the hazard-layer GeoJSON + `layers.json` |
| `uv run python pipeline/build_events.py` | Rebuild `flood-events.geojson`, `flood-reports.json`, `rainfall-records.json` |
| `uv run --group pipeline python pipeline/build_all.py` | Scaffold + download + ingest + build the GeoPackage, all four counties, one command |
| `uv run --group pipeline python pipeline/build_county_collections_geopackage.py` | Just the last step above — build the GeoPackage from whatever's already in `data/` |

Rebuild after changing anything the pipeline reads (`data/**`), the severity rules
in `src/rgv_flood/severity.py`, or the pipeline scripts themselves.

### Local county-collections GeoPackage

`pipeline/build_all.py` (see Setup, above) ends by building
`data/generated/county-collections.gpkg` from the canonical files in
`data/<county>-county/` — a queryable local relational/spatial database
covering all four counties. To rebuild just that last step, once `data/` is
already populated:

```bash
uv run --group pipeline python pipeline/build_county_collections_geopackage.py
```

`--output path/to/file.gpkg` places the artifact elsewhere. The build validates
GeoJSON geometry and canonical record identities, stores usable geometry as
native EPSG:4326 GeoPackage geometry, and writes atomically: a failed build
leaves an existing output untouched. This artifact is a local developer query
boundary; the app continues to read its precomputed static data as before.

The GeoPackage is organized as related tables rather than one generic data dump:

| Table | Purpose |
| --- | --- |
| `counties` | One row per canonical county collection. |
| `source_artifacts` | Every canonical input file's path, SHA-256, size, and artifact type. |
| `records` | Documented flood events and public reports, linked to a county and source artifact. |
| `weather_observations` | Weather-specific fields linked to their canonical record. |
| `spatial_layers` | Metadata for county flood-hazard and reference layers. |
| `layer_features` | Individual native-geometry features belonging to a spatial layer. |
| `records_fts` | Full-text search index for user-relevant record descriptions and source context. |
| `rtree_records_geometry` | Spatial bounding-box index for non-null record geometries. |
| `rtree_weather_observations_geometry` | Spatial bounding-box index for non-null weather geometries. |
| `rtree_layer_features_geometry` | Spatial bounding-box index for non-null layer-feature geometries. |

## Dependency groups

```bash
uv sync                       # app only (Flask + jinja-partials)
uv sync --group dev           # + pytest, ruff
uv sync --group pipeline      # + geopandas, shapely, pyproj, requests, beautifulsoup4
```

`--group pipeline` is needed for `pipeline/build_layers.py`,
`pipeline/build_county_collections_geopackage.py`, and `pipeline/build_all.py`
(which calls the GeoPackage builder). The app, `build_events.py`, and the tests
do not use it.

## Raw per-county data (gitignored)

Nothing under `data/<county>-county/` is committed except `README.md` and
`.gitkeep` placeholders (so the empty folders still exist). Everything a script
produces — `manifest.json`, `schemas/*.schema.json`, `sources/**/*.json`,
`flood-hazard-layers/*.geojson` + its `manifest.json`, `records/**/*.ndjson` —
is build output now, per the project rule: if a script makes it, it isn't
committed.

| Ignored | Rebuilt by |
| --- | --- |
| `manifest.json`, `schemas/*.schema.json`, `sources/**/*.json` | `scripts/scaffold_county_collections.py`, from the tracked template at `pipeline/schemas/` |
| `flood-hazard-layers/*.geojson`, `flood-hazard-layers/manifest.json` | `scripts/import_county_flood_data.py` — **needs the sibling `Flood Project/` working directory** (override the path with `RGV_FLOOD_PROJECT_RAW_DIR`), which is not itself a public, scripted download |
| `records/**/*.ndjson` | `scripts/ingest-noaa-*.mjs` — reproducible from public NOAA URLs, see below |
| `src/rgv_flood/static/data/*.json`, `*.geojson` | `pipeline/build_layers.py` and `pipeline/build_events.py` |

`pipeline/build_all.py` runs the first three end to end. The one thing nothing
here can produce without outside help is the `Flood Project/` directory itself
— that was a separate, earlier, manual data-acquisition effort (FEMA/TWDB/Census
downloads), not part of this repo. If you don't have it, `build_all.py` skips
that step with a warning and everything else still builds.

`sources/public-reports/official-local-news-2018-2021.json` on Hidalgo is the
other file with no generator — it documents a manual news-search pass, not a
mechanical pull. It only exists in git history and on disk now.

Everything here was previously committed; it was removed from tracking (`git rm
--cached`, kept on disk, nothing deleted) once the four counties' combined data
pushed `data/` past 200 MB. Older commits still contain it in history.

## One-off / data-acquisition scripts

`pipeline/build_all.py` runs all of these for you, in the right order, for all
four counties. Run one directly only if you want a single step in isolation.
No `uv` deps beyond stdlib; the `.mjs` scripts are plain Node with no packages.

| Script | Purpose |
| --- | --- |
| `scripts/scaffold_county_collections.py` | Creates/refreshes each `data/<county>-county/` folder: `manifest.json`, `schemas/` (copied from `pipeline/schemas/`), `sources/*.json` notes, `records/` + `sources/` skeleton |
| `scripts/download-noaa-source-files.mjs` | Downloads the raw Storm Events + GHCN-Daily `.csv.gz` files the two ingest scripts below need, into `tmp/noaa/` by default |
| `scripts/ingest-noaa-storm-events.mjs` | NOAA Storm Events → flood-event NDJSON, one county at a time |
| `scripts/ingest-noaa-ghcn-daily.mjs` | NOAA GHCN-Daily → weather-observation NDJSON, one county at a time |
| `scripts/import_county_flood_data.py` | Copies processed hazard GeoJSON in from the sibling `Flood Project/` dir, split per county |

```bash
uv run python scripts/scaffold_county_collections.py
node scripts/download-noaa-source-files.mjs              # -> tmp/noaa/
uv run python scripts/import_county_flood_data.py         # needs ../Flood Project/ (or $RGV_FLOOD_PROJECT_RAW_DIR)
```

### Re-ingesting the NOAA records (Node)

Both ingest scripts take a directory of downloaded `.csv.gz` files, write an
NDJSON file plus a JSON source note, and take a 4th argument selecting the
county (default is Hidalgo, so the original invocation still works unchanged):

```
node scripts/<script>.mjs  <gzip-directory>  <output.ndjson>  <source-note.json>  [county]
```

`scripts/download-noaa-source-files.mjs` fetches the raw files for all four
counties in one shot and prints the exact ingest commands to run afterward —
use that instead of downloading by hand. Manually, for reference:

**Storm events** — every annual detail file for 2000–2025 from
<https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/>
(`StormEvents_details-ftp_v1.0_d{YEAR}_c*.csv.gz`) go in one shared folder (all
counties are in the same national file, split by NOAA's `CZ_NAME`:
`HIDALGO`, `CAMERON`, `STARR`, or `WILLACY`):

```bash
node scripts/ingest-noaa-storm-events.mjs \
  tmp/noaa/storm-events \
  data/hidalgo-county/records/events-and-public-reports/noaa-storm-events.ndjson \
  data/hidalgo-county/sources/official-events/noaa-storm-events-2000-2025.json \
  HIDALGO
```

It filters to `STATE=TEXAS` and flood-type events, and **never deletes rows it
didn't generate**: Hidalgo's NDJSON also has 16 local-news / government reports
added by hand, and re-running the script reads them back out of the existing
file and keeps them (`[preserve] keeping 16 existing...`) rather than
overwriting the file wholesale.

**GHCN-Daily weather** — each county has its own hardcoded station set in
`ingest-noaa-ghcn-daily.mjs` (`STATIONS_BY_COUNTY`, picked by checking NOAA's
station list against that county's own TIGER boundary; the same IDs are
duplicated in `download-noaa-source-files.mjs` — keep both in sync if a station
set changes). Station files come from
<https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station/>, one folder per
county:

```bash
node scripts/ingest-noaa-ghcn-daily.mjs \
  tmp/noaa/ghcn-hidalgo \
  data/hidalgo-county/records/layers-and-weather/noaa-ghcn-daily-2000-2025.ndjson \
  data/hidalgo-county/sources/weather/noaa-ghcn-daily-2000-2025.json \
  hidalgo
```

It keeps PRCP / TMAX / TMIN / AWND for 2000-01-01 through 2025-12-31 and drops
rows with a nonblank NOAA quality flag.

After re-ingesting, rebuild the overlays:
`uv run python pipeline/build_events.py` and/or
`uv run --group pipeline python pipeline/build_county_collections_geopackage.py`
— both now cover all four counties.

## Data sources

| Layer | Source | Coverage |
| --- | --- | --- |
| Flood hazard zones | FEMA National Flood Hazard Layer (NFHL) | Cameron, Starr, Willacy |
| Flood hazard zones | Hidalgo County Drainage District No. 1 digitized 1981 FIRM (no FEMA digital data) | Hidalgo |
| Modeled flood extent | TWDB 2025 cursory floodplain dataset (Fathom 3 m) — contextual, not regulatory | all four |
| County boundaries | US Census TIGER/Line 2023 | all four |
| Flood events + weather | NOAA NCEI Storm Events + GHCN-Daily, 2000–2025 | all four counties — the map, event list, and rainfall records all merge them, filterable by the header county selector |
| Local news / government reports | Hidalgo County / City of McAllen / KRGV, tied to documented events | **Hidalgo only.** These 16 are hand-curated — someone read the local coverage for each event window and picked out real reports. No script produces them; the other three counties don't have any yet, not because the data doesn't exist but because nobody's done that research pass for them |

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
    js/map.js         Leaflet setup, layer toggles, event layer, address search, NWS alerts
    css/app.css
    data/             pipeline outputs the app serves as-is (all gitignored)
pipeline/
  build_all.py         one-command fresh-clone build: scaffold -> download -> ingest -> gpkg
  build_layers.py      hazard layers  -> static/data/*.geojson + layers.json
  build_events.py      NOAA records   -> flood-events / flood-reports / rainfall
  build_county_collections_geopackage.py  -> data/generated/county-collections.gpkg
  schemas/              tracked schema template scaffold_county_collections.py copies from
data/
  <county>-county/    entirely gitignored build output: manifest, schemas, sources,
                      records, flood-hazard-layers/  (see data/hidalgo-county/README.md)
scripts/              data-acquisition scripts build_all.py runs, in order (see above)
tests/
```

Config is overridable from the environment — e.g. `RGV_MAP_DATA_DIR` to point the
app at a different `static/data` directory (the test suite uses this).
