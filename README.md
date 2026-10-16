# RGV Flood Impact Visualizer

CSCI 4390 Senior Project by Danny McClain and Luis Garcia. Faculty adviser:
Sergei Chuprov.

A map for comparing flood-hazard information across Cameron, Hidalgo, Starr
and Willacy counties: hazard zones, drainage and flood-control works, dams, bridges,
recorded flooding and flood photos, NOAA flood events, rainfall, local reports,
live official alerts and address search, plus a page that sets
flood-insurance claims beside rainfall year by year since 1978.

Educational and comparative only. Not for emergency routing, engineering,
insurance, flood-depth estimates, or flood-zone certification. Follow official
emergency guidance.

## Stack

| Part | What it uses |
| --- | --- |
| Server | One FastAPI service (Uvicorn): the pages, a typed JSON API documented at `/docs`, vector tiles, static files, and the live-alert refresher |
| Data | One SQLite database, `data/generated/rgv-flood.sqlite3`, opened read-only by the app (WAL mode) |
| Pages | Jinja templates built from components, Alpine.js (CSP build) for behaviour, Tailwind CSS v4 compiled by Tailwind's standalone binary through `pytailwindcss` |
| Map | MapLibre GL JS on OpenStreetMap vector basemaps from OpenFreeMap (Positron in light mode, the default; Dark in dark mode) |
| Charts | Plotly.js, on the claims page only |
| Pipeline | Python with geopandas, shapely and GDAL: pulls every source and writes the database |
| Deployment | Docker image behind Caddy (HTTPS), built and published by GitHub Actions |

There is no Node and no JavaScript build step. Third-party front-end files
(MapLibre, Alpine, Plotly, the Public Sans font) are pinned by version and SHA-256 in
`src/rgv_flood/vendor.lock.json` and served by the app itself. Requires Python
3.13+ and [uv](https://docs.astral.sh/uv/); works the same on Windows, macOS
and Linux.

## Quick start

From the repository root:

```bash
uv sync --group dev --group pipeline
uv run --group pipeline python pipeline/build_all.py
uv run dev
```

Open <http://127.0.0.1:8000>.

- `build_all.py` builds the database. It downloads about 400 MB into the `tmp/`
  cache the first time; later runs reuse it. It is safe to run while the app is up.
- `uv run dev` fetches the pinned front-end files if they are missing, rebuilds
  the stylesheet whenever a template or script changes, and reloads the server
  on code changes.
- `uv run serve` runs it as in production: minified stylesheet, several workers
  (`RGV_WORKERS`, default 4).

## Using the map

- **Layers.** The left panel groups the layers: flood hazard, drainage and flood
  works, evidence of flooding, projects. Tick a layer to draw it; a group's own
  checkbox turns the whole group on or off and shows a dash when only some of
  it is on. The round "i" opens the layer's source card: what it is, who
  publishes it, how old it is, and what it should not be used for.
- **Severity colors.** Every hazard layer is colored by relative severity:
  red for severe, orange for moderate, blue for light, gray where the source
  gives no class. Each source's own zones are mapped to these three classes.
- **Dams.** Dams are their own row under drainage and flood works: the State
  Flood Plan's dams plus named dams it lacks that OpenStreetMap has.
- **Sub-options.** Some rows have options underneath while they are on: TWDB's
  modeled flood extent splits into the 1% and 0.2% annual-chance areas, and
  Hidalgo's flood photos into "photos you can open" and "photo locations only".
- **Popups.** Click anything on the map for its details. A Hidalgo flood photo
  shows the district's picture; a FEMA photo town (a large pink dot) opens a
  gallery of FEMA's photos of flooding there, placed at the town the caption
  names. The selected feature gets an orange ring.
- **Live alerts.** Current NWS warnings and advisories, TxDOT road closures and
  Hidalgo County notices, at the top of the right panel and counted in the header.
- **Flood events.** NOAA's flood events, filtered by type or year. Picking one
  flies to it and shows the rain at the nearest gauges that day (or the full
  day-before-to-day-after table), with local news and NWS reports from the same days.
  Picking the selected event again clears it.
- **Rainfall records, local reports, data sources.** The rest of the right
  panel: the wettest single days at the gauges, curated news and government
  reports, and every dataset behind the map with the date it was downloaded and
  the date the database was built.
- **County.** The county selector fits the map to that county and narrows the
  events, rainfall records, reports and alerts to it.
- **Basemap labels.** Town, road and place names show on the US side only;
  labels across the Rio Grande in Mexico are hidden. Water names stay.
- **Address search.** Type an address, or press `/`, to fly there.
- **Light and dark.** The page opens in light mode; the "Dark" checkbox in the
  header turns dark on, and the choice is remembered in that browser.
- **Phones.** Below tablet width the map, the layers and the events are three
  views, switched from the bar at the bottom.
- **Sharing.** The page address holds the county, the layers and sub-options
  that are on, the selected event and the map view, so a copied link opens
  exactly what you see.

## Claims & rainfall by year

`/claims` shows the four counties together or one at a time, 1978 to the last
full year:

- tiles for total claims, dollars paid, the worst year and its storm, and how
  closely claims follow a year's wettest day and its total rain (they follow
  the wettest day more);
- three column charts sharing the year axis: claims (or dollars paid, or claims
  per 1,000 policies), yearly rain, and the wettest day of the year. Hovering a
  year shows it in all three and highlights it in the table; each chart can be
  viewed as a table;
- a year-by-year table with claims, payments, the claims rate, rain, the
  wettest day and the storm FEMA named.

Rain is the average of the gauges that reported on at least 330 days of the
year. Dollars are as paid, not adjusted for inflation. Policy counts start in 2009.

## The API

Every page reads the same read-only JSON endpoints, documented with their exact
responses at `/docs`:

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/layers` | The layer panel: groups, layers, legends, sub-options, sources |
| `GET /api/v1/layers/{id}.geojson` | A layer's GeoJSON, sent pre-compressed |
| `GET /api/v1/tiles/{id}/{z}/{x}/{y}.pbf` | Vector tiles of the layers over 1 MB compressed (the two TWDB layers) |
| `GET /api/v1/events`, `/api/v1/events.geojson` | NOAA flood events, filterable by county, type and year |
| `GET /api/v1/events/{id}/context` | One event's gauge rain, curated reports and NWS reports |
| `GET /api/v1/rainfall-records` | The wettest single days at the gauges |
| `GET /api/v1/reports` | Curated local news and government reports |
| `GET /api/v1/live-signals`, `/api/v1/live-signals.geojson` | Current official alerts and when they were last refreshed |
| `GET /api/v1/history` | Claims, payments, policies, rain and events, year by year |
| `GET /api/v1/sources` | Every dataset's publisher, link, download date and size; the build date |
| `GET /api/v1/geocode?q=` | Address search, proxied to Nominatim (cached, one request a second upstream, 30 a minute per visitor) |
| `GET /health` | Status for Docker and Caddy; 503 when the database is missing |

The county filter is one of `cameron`, `hidalgo`, `starr`, `willacy`. JSON
responses carry ETags; layer files and tiles are cached by browsers and proxies.

## Data and database

Everything lives in `data/generated/rgv-flood.sqlite3`, built by
`pipeline/build_all.py`; see [pipeline/README.md](pipeline/README.md) for each step.

| Table | Holds |
| --- | --- |
| `layers` | Every map layer: its description, its place in the layer panel, and the GeoJSON the map draws |
| `layer_tiles` | Vector tiles of the big layers |
| `flood_events` | Flood-type events from NOAA's Storm Events Database, 1996–2025 |
| `flood_reports` | Hand-curated local news and government flood reports |
| `nws_flood_reports` | Flooding reported to the National Weather Service in Brownsville, 2005 on |
| `weather_stations`, `weather_observations` | NOAA GHCN-Daily stations and their daily rain readings, 1978–2025 |
| `rainfall_station_years` | Each gauge's yearly rain, wettest day and days reported |
| `nfip_claims`, `nfip_policies_by_year` | Every NFIP flood-insurance claim since 1978; policies per county and year since 2009 |
| `data_sources` | Where each dataset came from and when it was downloaded |
| `build_info` | When the database was built |
| `live_signals` | Current official alerts, road conditions and notices, refreshed while the app runs |

The only data files in the repository are the seed files in `data/seed/`:
flood-hazard geometry, curated reports and yearly NFIP policy counts that no
publisher offers as a scripted download. See [data/seed/README.md](data/seed/README.md).

`pipeline/fetch_ml_inputs.py` is separate from the app: it gathers the public
inputs for the planned Hidalgo flood-susceptibility model (elevation, NLCD,
soils, Atlas 14 rainfall, Overture buildings and roads, NFIP claims and
policies, Hidalgo drainage-district layers) into the gitignored `data/ml/raw/`.

## Configuration

Settings are environment variables, all optional:

| Variable | Default |
| --- | --- |
| `RGV_DATABASE` | `data/generated/rgv-flood.sqlite3` |
| `RGV_LIVE_SIGNALS_SCHEDULER_ENABLED` | `true` (refreshes alerts at startup and every interval) |
| `RGV_LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS` | `900` |
| `RGV_LIVE_SIGNALS_SCHEDULER_LOCK_FILE` | next to the database (one refresher per host) |
| `RGV_BASEMAP_LIGHT_STYLE`, `RGV_BASEMAP_DARK_STYLE` | OpenFreeMap Positron and Dark |
| `RGV_GEOCODER_URL`, `RGV_GEOCODER_USER_AGENT` | Nominatim, with the project's name |
| `RGV_LOG_LEVEL` | `INFO` (one JSON log line per request) |

## Deployment

The app runs on the university's Azure VM as one Docker image (database
included) behind Caddy, which handles HTTPS. GitHub Actions tests every push,
and the release workflow builds the database and the image on pushes to `main`,
on demand, and on the first of each month so the NOAA and FEMA data stay
current. On the server: `docker compose pull && docker compose up -d`. Full
setup in [deploy/README.md](deploy/README.md).

## Development and testing

```bash
uv run playwright install chromium   # once, for the browser tests
uv run pytest
uv run ruff check .
```

- `tests/api/`: every endpoint, the pages, assets, caching and security headers.
- `tests/browser/`: the real app in Chromium: the map, layers and sub-options,
  popups and galleries, the side panels, search, shareable links, the phone
  layout, themes, and the claims charts.
- The rest: the pipeline.

Interface text lives in `src/rgv_flood/i18n/en.json`, so a Spanish version is
a matter of adding `es.json`. The visual design follows the Claude Design
handoff kept in `docs/design/handoff/`.

## Repository layout

| Path | What it is | In Git |
| --- | --- | --- |
| `src/rgv_flood/app.py` | The FastAPI app: settings, database, middleware, routers, the live-alert refresher | yes |
| `src/rgv_flood/api/` | One module per group of endpoints, and the response models | yes |
| `src/rgv_flood/data_access.py` | Every database query | yes |
| `src/rgv_flood/templates/` | `base.html`, `map.html`, `claims.html` and their `components/` | yes |
| `src/rgv_flood/static/` | `css/input.css` (tokens and components), `js/` (`map/`, `panels/`, one entry per page in `pages/`), `basemap/offline.json`, `favicon.svg` | yes |
| `src/rgv_flood/static/css/site.css`, `static/vendor/`, `static/fonts/` | Built stylesheet and fetched third-party files | no |
| `pipeline/` | The build scripts and the live-alert pollers; see [pipeline/README.md](pipeline/README.md) | yes |
| `tests/` | API, browser and pipeline tests | yes |
| `deploy/`, `.github/workflows/` | Dockerfile, Compose with Caddy, the server guide; CI and the monthly release | yes |
| `data/seed/` | The seed files (see above) | yes |
| `data/generated/` | The database | no |
| `tmp/` | Download cache of the publishers' files; safe to delete | no |
| `data/ml/raw/` | Downloads from `fetch_ml_inputs.py` | no |

## Troubleshooting

- `uv` errors: run `uv sync --group dev --group pipeline` again.
- The page has no styling: the stylesheet isn't built; run `uv run dev` or `uv run serve`.
- "No data yet" on the page: run `build_all.py`.
- A build fails on a download: check network access to NOAA, Overture, FEMA,
  TWDB, the Census Bureau, Iowa Environmental Mesonet, Wikimedia Commons, the
  cities' ArcGIS services and the Hidalgo drainage district, then re-run;
  finished downloads stay in `tmp/`.
- A layer is missing after a build: its publisher was unreachable. The build names it; re-run.
- Live alerts don't show: source outages are logged and the rest of the app keeps working.

## Hidalgo Drainage District (HCDD1) data

The mapped flooding, flood photos, drainage network and bond-project layers
come from Hidalgo County Drainage District No. 1 (<https://www.hcdd1.org>),
which publishes its data through a public ArcGIS Online account (no login or
API key). All layers are ArcGIS REST feature services under one base URL:

```
https://services7.arcgis.com/JSUhwVSJhyVkcN3Q/arcgis/rest/services
```

| Request | URL pattern |
| --- | --- |
| List every service | `<base>?f=json` |
| One service's layers | `<base>/<Service>/FeatureServer?f=json` |
| Layer fields and metadata | `<base>/<Service>/FeatureServer/<layer>?f=json` |
| Feature count | `<base>/<Service>/FeatureServer/<layer>/query?where=1=1&returnCountOnly=true&f=json` |
| Download as GeoJSON | `<base>/<Service>/FeatureServer/<layer>/query?where=1=1&outFields=*&outSR=4326&f=geojson&resultOffset=0&resultRecordCount=1000` |

Servers cap how many features one response returns, so `pipeline/public_sources.py`
asks for 1,000 at a time and advances `resultOffset` until a page comes back empty.

| Service / layer | Features | Becomes |
| --- | --- | --- |
| `Historical_Flooding_Layer` 0–3 (photos), `Hanna_Geotagged_Photos` | ~16k | Flood photos and photo locations; layers 1 and 2 (June 2019, Sept 2018) publish the image itself, about 4,850 photos |
| `Historical_Flooding_Layer` 4–9 (extents, 2008–2020) | ~1,200 | Mapped flooding |
| `HCDD1_System`, `Future_System`, `Detention_Ponds`, `Gate_Pumps_New` | ~1,750 | Drainage network |
| `2012_Bond_Program`, `2018_Bond_Program`, `2023_Bond` | ~200 | Drainage improvement projects |
| `FEMA_Hidalgo_FIRM`, `LOMR_CLOMR`, `Rain_n_Stream_Gauges`, `Ditch_Maintenance`, others | various | Downloaded for the model work |

Other public APIs the pipeline uses:

| Data | API |
| --- | --- |
| NFIP claims (v3) | `https://www.fema.gov/api/open/v3/NfipClaims` |
| NFIP policies (v2; retired by FEMA, counts kept in `data/seed/`) | `https://www.fema.gov/api/open/v2/FimaNfipPolicies` |
| Elevation (3DEP) | `https://tnmaccess.nationalmap.gov/api/v1/products` |
| Land cover / imperviousness (NLCD) | `https://www.mrlc.gov/geoserver/mrlc_download/wcs` |
| Soils (SSURGO) | `https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest` |

### HCDD1's own maps and dashboards

Found through the ArcGIS Online search API and hcdd1.org; listed as found, not
each checked to still load.

| Name | Link |
| --- | --- |
| HCDD1 Flood Web Map Application | <https://www.arcgis.com/home/item.html?id=e98554156b5e4bcd84bbe0e2d10c2764> |
| HCDD1 Flood Zone Map (Experience) | <https://experience.arcgis.com/experience/bcb86ca21dc14729bb5c1a5814ca91ad> |
| HCDD1 Master Web Map Application | <https://www.arcgis.com/home/item.html?id=43d4be942e7e4e66b35f8220da82cb89> |
| HCDD1 System Map (Experience) | <https://experience.arcgis.com/experience/73feb7978e4c4a518787e6a9dc1f1d69> |
| Working System Map | <https://www.arcgis.com/home/item.html?id=a3dd6fddb57846168ed9e1a9f13782b0> |
| Storm Event Webmap | <https://www.arcgis.com/home/item.html?id=bdfd390479054ca0943275bc4e0662ec> |
| Flood Damages June 2018 | <https://www.arcgis.com/home/item.html?id=f9a644ef576943549ac75382d0ba56e2> |
| HCDD1 Damage Assessment | <https://www.arcgis.com/home/item.html?id=9286802c6d1540de854e65a28989a002> |
| Hidalgo County FEMA Damage Assessment | <https://www.arcgis.com/home/item.html?id=53b2d29760e94fc88229d7524dbba6e5> |
| 2012 Bond Dashboard | <https://www.arcgis.com/home/item.html?id=4bbb6b3959124f62bf7b30389a6dddce> |
| 2018 Bond Dashboard | <https://hcdd1.maps.arcgis.com/apps/dashboards/d3c9a895241a49e1a28a762674131994> |
| 2023 Bond Dashboard | <https://hcdd1.maps.arcgis.com/apps/dashboards/f7722aadbef74bf29d76d144d49390e8> |
| 2023 Bond Program (StoryMap) | <https://www.arcgis.com/home/item.html?id=8fe792773ef54022820df1e07b988789> |
| 2012 / 2018 / 2023 Bond web maps | <https://www.arcgis.com/home/item.html?id=dd80cec1e78044e183637fcd0d960f22>, <https://www.arcgis.com/home/item.html?id=def43e7d9fe54eb8a9c3a60967411d10>, <https://www.arcgis.com/home/item.html?id=7ba2f73521464879ba10acc62290c472> |
| HCDD1 District Projects | <https://www.arcgis.com/home/item.html?id=40da5a923154485cac2256bf3daec571> |
| HCDD1 Master Dashboard | <https://www.arcgis.com/home/item.html?id=8abf134d9c83476fbe57f923e03028c6> |

The district's data terms of use were not found; the layers credit "Hidalgo
County Drainage District No. 1". Confirm reuse with the district before
publishing this project outside the course.

## Sources and acknowledgments

Hazard data comes from FEMA, Hidalgo County Drainage District No. 1 and TWDB;
drainage and flood works from TWDB's State Flood Plan, Census TIGER/Line and the
cities of Harlingen and Brownsville; boundaries from Census TIGER/Line; events
and weather from NOAA; reported flooding from NWS (archived by Iowa
Environmental Mesonet); insurance claims and policies from OpenFEMA; FEMA's
flood photos from Wikimedia Commons; bridges and the dams the State Flood Plan lacks from Overture Maps
Foundation; live alerts from NWS, TxDOT and Hidalgo County; basemaps from
OpenFreeMap and OpenStreetMap. Curated local reports cover Hidalgo County.

Contributions should keep source attribution and source-supplied geometry
intact, include focused tests, never infer live conditions, and never present
this tool as emergency or regulatory guidance.

No separate license is currently declared. Built by Danny McClain and Luis
Garcia with guidance from Sergei Chuprov.
