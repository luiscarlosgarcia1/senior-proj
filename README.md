# RGV Flood Impact Visualizer

CSCI 4390 Senior Project by Danny McClain and Luis Garcia. Faculty adviser:
Sergei Chuprov.

## Overview

A browser map for comparing flood-hazard information across Cameron, Hidalgo,
Starr, and Willacy counties. Includes hazard layers, at-risk infrastructure
(bridges, dams), documented flood events, rainfall, local reports, official
live signals, and address search.

Educational and comparative only. Not for emergency routing, engineering,
insurance, flood-depth estimates, or flood-zone certification. Follow official
emergency guidance.

## Technology Stack

- Flask, Jinja templates, HTMX, Leaflet
- One SQLite database holds all the data; the app reads nothing else
- Python data pipeline (geopandas, shapely) that pulls each source and writes it to that database
- Vanilla JavaScript ES modules for the map; no Node or build step
- NOAA, FEMA, TWDB, Census, NWS, TxDOT, and local government sources

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

## Quick Start

From the repository root:

```bash
uv sync --group dev --group pipeline
uv run --group pipeline python pipeline/build_all.py
uv run flask --app rgv_flood run --debug
```

Open <http://127.0.0.1:5000>.

`build_all.py` is the one build command. It pulls every source into memory and
writes it to a single SQLite database, `data/generated/rgv-flood.sqlite3`: map
layers, flood events, local reports, weather records and live signals. The app
reads only that database, never data files. Re-run the build after changing
pipeline inputs or rules; it is safe to run while the app is up. The first run
downloads about 400 MB into the `tmp/` cache, and later runs reuse it. See
[pipeline/README.md](pipeline/README.md) for the tables and the individual steps.

Flask refreshes official live signals at startup and every 15 minutes. Set
`RGV_LIVE_SIGNALS_SCHEDULER_ENABLED=false` to disable it, or set
`RGV_LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS` to change the interval.

## Troubleshooting

- `uv` errors: run `uv sync --group dev --group pipeline` again.
- Map has no layers or events: run `build_all.py` (it builds `data/generated/rgv-flood.sqlite3`).
- Build fails on a download: confirm network access to NOAA, Overture, FEMA, the Census Bureau and
  the Hidalgo drainage district, then re-run; finished downloads are kept in `tmp/`.
- A layer is missing after a build: its publisher was unreachable. The build says which; re-run it.
- Live signals unavailable: source outages are logged; the app remains usable.

## Data and Database

Everything lives in one SQLite file, `data/generated/rgv-flood.sqlite3`:

| Table | Holds |
| --- | --- |
| `layers` | Every map layer: its description and the GeoJSON the map draws |
| `flood_events` | Flood-type events from NOAA's Storm Events Database, 2000–2025 |
| `flood_reports` | Hand-curated local-news and government flood reports |
| `weather_stations`, `weather_observations` | NOAA GHCN-Daily stations and their daily readings, 2000–2025 |
| `data_sources` | Where each dataset came from and when it was downloaded |
| `live_signals` | Current official alerts, road conditions and notices, refreshed while the app runs |

The build scripts download from the publishers, hold the data in memory and
write these tables. The only data files in the repository are the seed files in
`data/seed/`: flood-hazard geometry and curated reports that no publisher offers
as a scripted download. Set `RGV_DATABASE` to point the app at a database
somewhere else, which is all a deployment needs alongside the code.

`pipeline/fetch_ml_inputs.py` is separate from the app: it gathers the public
inputs for the planned Hidalgo flood-susceptibility model (elevation, NLCD,
soils, Atlas 14 rainfall, Overture buildings/roads, NFIP claims and policies,
Hidalgo drainage-district layers) into the gitignored `data/ml/raw/`.

## Hidalgo Drainage District (HCDD1) Data and Visualizations

The flood-evidence, drainage and bond-project overlays come from Hidalgo County
Drainage District No. 1 (<https://www.hcdd1.org>), which publishes its data
through a public ArcGIS Online account (no login or API key).

### REST API that pulls the data

All layers are ArcGIS REST feature services under one base URL:

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

Servers cap how many features one response can return, so the script asks for
1,000 at a time and advances `resultOffset` until a page comes back empty.
`pipeline/public_sources.py` does this for the layers listed in its
`HCDD1_LAYERS` table, and `pipeline/build_layers.py` turns the ones below into
map layers in the database:

```bash
uv run --group pipeline python pipeline/build_layers.py
```

| Service / layer | Features | Becomes |
| --- | --- | --- |
| `Historical_Flooding_Layer` 0–3 (photos), `Hanna_Geotagged_Photos` | ~16k kept | Flood response photos |
| `Historical_Flooding_Layer` 4–9 (extents, 2008–2020) | ~1,200 | Mapped flooding |
| `HCDD1_System`, `Future_System`, `Detention_Ponds`, `Gate_Pumps_New` | ~1,750 | Drainage network |
| `2012_Bond_Program`, `2018_Bond_Program`, `2023_Bond` | ~200 | Drainage improvement projects |
| `FEMA_Hidalgo_FIRM`, `LOMR_CLOMR`, `Rain_n_Stream_Gauges`, `Ditch_Maintenance`, others | various | Downloaded for the ML work, not yet on the map |

Other public APIs used for the insurance-claims layer and model inputs:

| Data | API |
| --- | --- |
| NFIP claims (v3) | `https://www.fema.gov/api/open/v3/NfipClaims` (OData: `$filter`, `$top`, `$skip`) |
| NFIP policies (v2, removed by FEMA 2026-10-15) | `https://www.fema.gov/api/open/v2/FimaNfipPolicies` |
| Elevation (3DEP) | `https://tnmaccess.nationalmap.gov/api/v1/products` |
| Land cover / imperviousness (NLCD) | `https://www.mrlc.gov/geoserver/mrlc_download/wcs` (WCS 2.0.1) |
| Soils (SSURGO) | `https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest` |

### HCDD1's own visualizations

HCDD1 publishes its own maps and dashboards from the same account. These are
useful to compare against this project's overlays and for their legends and
descriptions. Links were found through the ArcGIS Online search API and
the hcdd1.org homepage; they are listed as discovered, not individually
verified to still load.

**Flood and system maps**

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

**Projects and bond programs**

| Name | Link |
| --- | --- |
| 2012 Bond Dashboard | <https://www.arcgis.com/home/item.html?id=4bbb6b3959124f62bf7b30389a6dddce> |
| 2018 Bond Dashboard | <https://hcdd1.maps.arcgis.com/apps/dashboards/d3c9a895241a49e1a28a762674131994> |
| 2023 Bond Dashboard | <https://hcdd1.maps.arcgis.com/apps/dashboards/f7722aadbef74bf29d76d144d49390e8> |
| 2023 Bond Program (StoryMap) | <https://www.arcgis.com/home/item.html?id=8fe792773ef54022820df1e07b988789> |
| 2012 / 2018 / 2023 Bond web maps | <https://www.arcgis.com/home/item.html?id=dd80cec1e78044e183637fcd0d960f22>, <https://www.arcgis.com/home/item.html?id=def43e7d9fe54eb8a9c3a60967411d10>, <https://www.arcgis.com/home/item.html?id=7ba2f73521464879ba10acc62290c472> |
| HCDD1 District Projects | <https://www.arcgis.com/home/item.html?id=40da5a923154485cac2256bf3daec571> |
| HCDD1 Master Dashboard | <https://www.arcgis.com/home/item.html?id=8abf134d9c83476fbe57f923e03028c6> |

The district's data terms of use were not found; the overlays here credit
"Hidalgo County Drainage District No. 1". Confirm reuse with the district before
publishing this project outside the course.

## Repository Layout

| Path | What it is | In Git |
| --- | --- | --- |
| `src/rgv_flood/` | The Flask app: `views/`, `data_access.py` (every database query), templates, and the map's ES modules in `static/js/` | yes |
| `pipeline/` | The build scripts and the live-signal pollers; see [pipeline/README.md](pipeline/README.md) | yes |
| `tests/` | Tests for the app and the pipeline | yes |
| `data/seed/` | Seed files: FEMA, TWDB and county-boundary GeoJSON and Hidalgo's 16 curated reports. The only data in the repository; see [data/seed/README.md](data/seed/README.md) | yes |
| `data/generated/` | The database, `rgv-flood.sqlite3` | no |
| `tmp/` | Download cache: publishers' files as downloaded, so a rebuild does not fetch them again. Safe to delete | no |
| `data/ml/raw/` | Downloads from `fetch_ml_inputs.py` for the planned model | no |

Nothing generated is committed and the app reads no data files, so after a fresh
clone `build_all.py` has to run once before the map has anything to show.

## Development and Testing

```bash
uv run pytest
uv run ruff check .
```

Keep source attribution and source-supplied geometry intact; do not infer live
conditions.

## Sources, Contributing, License, and Acknowledgments

Source coverage is documented in the data and pipeline artifacts. Hazard data
comes from FEMA, Hidalgo County Drainage District No. 1, and TWDB; boundaries
from Census TIGER/Line; events and weather from NOAA; bridges and dams from
Overture Maps Foundation; live signals from NWS, TxDOT, and Hidalgo County.
Local reports currently cover Hidalgo County only.

Contributions should preserve source attribution, include focused tests, and
avoid presenting this tool as emergency or regulatory guidance.

No separate license is currently declared. Built by Danny McClain and Luis
Garcia with guidance from Sergei Chuprov.
