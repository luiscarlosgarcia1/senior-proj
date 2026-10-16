# Data pipeline

Builds and maintains the project's one database,
`data/generated/rgv-flood.sqlite3`. Every script here pulls its sources into
memory and writes straight to that database. Nothing is generated as loose data
files, and the app reads nothing else.

```bash
uv run --group pipeline python pipeline/build_all.py     # about 2 minutes once downloads are cached
```

The database is gitignored build output, so `build_all.py` must run once after a
clone before the app has anything to serve. It is safe to re-run at any time,
including while the app is running: each step replaces only its own tables, in
a single transaction.

## The central database

Every table is defined in `database.py`. Every query the app runs is in
`src/rgv_flood/data_access.py`.

| Table | One row per | Written by |
| --- | --- | --- |
| `layers` | map layer: title, description, source, limitation and links, its place in the layer panel (group, row, legend, sub-options), and the map-ready GeoJSON the browser draws (stored gzipped and sent as is) | `build_layers.py` |
| `layer_tiles` | vector tile (gzipped MVT, XYZ numbering) of a layer over 1 MB compressed | `build_layers.py` |
| `flood_events` | flood-type event in NOAA's Storm Events Database, 1996–2025, with NOAA's coordinate and the point the map plots | `build_events.py` |
| `flood_reports` | hand-curated local-news or government report tied to a flood | `build_events.py` |
| `weather_stations` | GHCN-Daily station used for a county | `build_events.py` |
| `weather_observations` | daily rain reading at a station, 1978–2025 | `build_events.py` |
| `rainfall_station_years` | station and year: days with a rain reading, total, wettest day, days over 2 inches | `build_history.py` |
| `nfip_claims` | NFIP flood-insurance claim in the four counties, 1978 on | `build_history.py` |
| `nfip_policies_by_year` | county and year: NFIP policies in force, 2009 on | `build_history.py` |
| `nws_flood_reports` | flood, flash flood, heavy rain or coastal flood report to NWS Brownsville, 2005 on | `build_history.py` |
| `data_sources` | dataset loaded into the database: publisher, URL, when it was downloaded, how many records | every build script |
| `build_info` | `built_at`: when `build_all.py` last finished | `build_all.py` |
| `live_signals` | current official alert, road condition or county notice | `run_*.py`, while the app runs |
| `live_signal_runs`, `live_signal_tombstones` | bookkeeping for live-signal polls and expired signals | `run_*.py` |

Open the file with any SQLite tool to look around:

```bash
sqlite3 data/generated/rgv-flood.sqlite3 "select id, publisher, retrieved_at, record_count from data_sources"
```

## Where the data comes from

| Source | How the build gets it |
| --- | --- |
| NOAA Storm Events, NOAA GHCN-Daily | downloaded (`noaa.py`) |
| Overture Maps bridges and dams | downloaded (`overture.py`) |
| Hidalgo drainage district layers, FEMA NFIP claims, Census tracts, water lines and places, TWDB State Flood Plan, Harlingen and Brownsville drainage, NWS storm reports, FEMA flood photos on Wikimedia Commons | downloaded (`public_sources.py`) |
| FEMA NFHL, TWDB floodplain, Hidalgo 1981 FIRM, county boundaries | seed files in `data/seed/<county>/` |
| Curated local flood reports | seed file `data/seed/hidalgo/public-reports.ndjson` |
| NFIP policies per county and year | seed file `data/seed/nfip-policies-by-year.csv` (FEMA retired the source) |

**Download cache.** Downloads are kept in the gitignored `tmp/` folder exactly
as the publisher sent them, so a rebuild fetches only what is missing and works
offline once the cache is full. It is only a cache: delete `tmp/` and the next
build downloads everything again (about 400 MB). Nothing parsed or generated is
written there.

**Seed files.** `data/seed/` holds the few inputs no publisher offers as a
scripted download. They are the only data files in the repository; see
[data/seed/README.md](../data/seed/README.md) for what each one is.

## `build_events.py` — events, reports, weather

```bash
uv run python pipeline/build_events.py                       # ~12 s
```

Reads NOAA's yearly Storm Events files once for all four counties and keeps the
flood-type events (`noaa.py`), loads each county's GHCN-Daily stations and
readings, and adds the curated reports from the seed folder.

An event whose NOAA coordinate falls outside its own county's boundary is kept
but not plotted: `source_lon`/`source_lat` hold what NOAA published, `lon`/`lat`
are null, and `geometry_note` says why. Stations are listed in
`noaa_stations.py`. Local reports exist for Hidalgo only; the other three
counties have none because nobody has done that hand-curation pass yet.

## `build_history.py` — claims, policies, reported flooding, gauge years

```bash
uv run python pipeline/build_history.py
```

Loads every NFIP claim FEMA publishes for the four counties, the yearly policy
counts from the seed file, and the flood reports made to NWS Brownsville since
2005 (from the Iowa Environmental Mesonet archive; a report NWS re-issued is
kept once). Then works out each gauge's yearly totals from
`weather_observations`, so it runs after `build_events.py`. The app's
year-by-year page reads these tables; a gauge's year counts toward a year's
rain only if it reported on at least 330 days.

`seed_nfip_policies.py` regenerates the policy seed file from a saved copy of
FEMA's retired v2 policies export; the build never runs it.

## `build_layers.py` — map layers

```bash
uv run --group pipeline python pipeline/build_layers.py      # ~90 s
```

For each hazard layer in the seed folder: reprojects to EPSG:4326, clips FEMA
NFHL to the true county boundary, assigns `relative_class` from
`rgv_flood.severity`, dissolves adjacent same-class polygons, and simplifies
geometry. Bridges are kept as individual features (no severity, no
dissolve) and only where they touch a county's real boundary, since the
bounding box used to query Overture also covers a strip of Mexico.

| `layers.id` | From |
| --- | --- |
| `county-boundaries` | TIGER county polygons, all four counties |
| `fema-nfhl` | FEMA NFHL — Cameron, Starr, Willacy |
| `hidalgo-firm-1981` | Hidalgo County DD No. 1 digitized 1981 FIRM |
| `twdb-cursory-1in100` / `-1in500` | TWDB 2025 cursory floodplain, all four |
| `overture-bridges` | Overture Maps |
| `waterways` | Census TIGER 2023 linear water: drains, canals, resacas and creeks, all four, except lines a local layer already maps |
| `flood-infrastructure` | TWDB State Flood Plan: dams, levees, sea walls, storm drains, low-water crossings, coastal works; plus named Overture dams the plan lacks |
| `city-drainage` | Harlingen storm ditches, ponds and sewers; Brownsville drainage ditches |
| `hcdd1-flood-extents`, `-flood-photos`, `-drainage`, `-bond-projects` | Hidalgo drainage district's published layers |
| `fema-flood-photos` | FEMA's flood photos on Wikimedia Commons, one point per town a caption names (Census place point) |
| `flood-projects` | TWDB State Flood Plan: ongoing and recommended flood projects |
| `nws-flood-reports` | the `nws_flood_reports` table, as points |
| `nfip-claims-by-tract` | FEMA NFIP claims per census tract |

The code is split by concern: `build_layers.py` (hazard and infrastructure
builders, and the layer-id → builder table that drives `main()`),
`evidence_layers.py` (drainage-district and insurance-claims layers),
`regional_layers.py` (the State Flood Plan, Census water, city drainage and NWS
report layers, each labelled with the county holding it), and
`layer_meta.py` (descriptions, limitations and links to each publisher's own
map).

Flood photos carry a `photo_url` wherever the drainage district publishes the
image (as an ArcGIS attachment). Only the listing of attachments is downloaded;
the images stay on the district's server and the map links to them.

**Where sources overlap, one is kept.** A Census water line that runs along a
drainage-district channel or a Harlingen or Brownsville ditch for 80% of its
length is left out, since the local line carries the ditch's name and owner.
An Overture dam within about 300 m of a State Flood Plan dam is the same dam;
Overture adds only named dams the plan lacks. The plan's lakes (listed as
ponds), parks, wetlands and "otherwise protected areas" are not flood works and
are left out. GHCN-Daily readings are kept for rain only: nothing reads
temperature or wind.

**Vector tiles.** A layer whose gzipped GeoJSON is over 1 MB (today the two
TWDB layers) is also cut into vector tiles, zoom 7 to 14, by GDAL
(`layer_tiles.py`), and the app serves those instead of the whole file.

**The layer panel.** `layer_meta.py`'s `PANEL` table gives each layer its group,
row, short label and legend; layers sharing a row (TWDB 1% and 0.2%) become that
row's sub-options, and `PARTS` adds sub-options within one layer (Hidalgo photos
you can open, photo locations).

The database runs in WAL mode, so the app's readers never wait on the
live-alert refresher's writes; `build_all.py` folds the WAL in before it compacts.

If a publisher can't be reached and its files aren't cached, that one layer is
left out, the rest are still written, and the script exits with an error naming
the missing layer.

Needs `OGR_GEOJSON_MAX_OBJ_SIZE=0` (the script sets it) — a few FEMA polygons
exceed GDAL's default per-feature size cap.

## Live signals

`run_nws.py`, `run_hidalgo_rss.py` and `run_drivetexas.py` each poll one official
source and update the `live_signals` table through `live_signals.py`
(`LiveSignalStore`). The app runs all three on a timer; each can also be
run by hand, and takes `--output` to write to a different database file.
`run_live_signal_fixture.py` loads the test fixture instead of a live source.

## `fetch_ml_inputs.py` — inputs for the Hidalgo model

```bash
uv run --group pipeline python pipeline/fetch_ml_inputs.py [--only hcdd1,nfip,...]
```

Separate from the app build. Gathers elevation, NLCD, soils, rainfall-frequency
grids, Overture layers, NFIP claims and policies, and the drainage district's
published layers into the gitignored `data/ml/raw/` for the planned
flood-susceptibility model. Re-runs skip files already present.

## Shared helpers

| Module | What it holds |
| --- | --- |
| `database.py` | Every table definition, and how a build script replaces its tables |
| `paths.py` | Where things live: the database, the seed folder, the download cache |
| `net.py` | HTTP GET for bytes, text and JSON, plus resumable downloads with retries |
| `jsonio.py` | Reading NDJSON, canonical (sorted, compact) JSON, GeoJSON feature collections |
| `rgv_flood.counties` | The four counties: slugs, FIPS codes, names, bounding box (shared with the app) |

## Conventions

- Reproject everything to EPSG:4326.
- Simplify geometry only where visual meaning is retained.
- Every hazard feature keeps `source`, `original_category`, and `relative_class`.
- Never invent a coordinate. NOAA rows with an obviously wrong `BEGIN_LON/LAT`
  keep the record and drop the plotted point rather than guessing a location.
- Keep what the publisher sent: values are stored without unit conversion, and
  a source's own classification (such as NOAA's event type) is used as is.
