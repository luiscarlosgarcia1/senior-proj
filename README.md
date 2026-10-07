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
- Python data pipeline; SQLite live-signal snapshots
- NOAA, FEMA, TWDB, Census, NWS, TxDOT, and local government sources

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Node 18+ for a
fresh historical-data build.

## Quick Start

From the repository root:

```bash
uv sync --group dev --group pipeline
uv run --group pipeline python pipeline/build_all.py
uv run --group pipeline python pipeline/build_layers.py
uv run python pipeline/build_events.py
uv run flask --app rgv_flood run --debug
```

Open <http://127.0.0.1:5000>.

`build_all.py` prepares the historical source data and local GeoPackage.
`build_layers.py` and `build_events.py` create the smaller files the Flask app
serves. Re-run the build steps after changing pipeline inputs or rules.

For the Hidalgo flood-evidence, drainage, bond-project and insurance-claims
overlays, run `uv run --group pipeline python scripts/fetch_ml_inputs.py --only hcdd1,nfip,tracts`
before `build_layers.py`; without those downloads the layers are simply skipped.

Flask refreshes official live signals at startup and every 15 minutes. Set
`RGV_LIVE_SIGNALS_SCHEDULER_ENABLED=false` to disable it, or set
`RGV_LIVE_SIGNALS_REFRESH_INTERVAL_SECONDS` to change the interval.

## Troubleshooting

- `uv` errors: run `uv sync --group dev --group pipeline` again.
- Map has no layers: run `build_layers.py` and `build_events.py`.
- Fresh data build fails: confirm Node 18+ and network access to source data.
- Live signals unavailable: source outages are logged; the app remains usable.

## Data Pipeline and Outputs

`pipeline/build_all.py` is the normal historical-data entry point. It scaffolds
county data, downloads and ingests reproducible NOAA records, imports Overture
Maps bridges and dams (clipped to each county's real boundary, not just a
bounding box — the RGV box also covers a strip of Mexico), and builds
`data/generated/county-collections.gpkg`.

`scripts/fetch_ml_inputs.py` gathers the public inputs for the planned Hidalgo
flood-susceptibility model (elevation, NLCD, soils, Atlas 14 rainfall, Overture
buildings/roads, NFIP claims and policies, Hidalgo drainage-district flood
photos and infrastructure) into the gitignored `data/ml/raw/`.

The Flask app reads precomputed layers and summaries from
`src/rgv_flood/static/data/`. Live-source snapshots are separate in
`data/generated/live-signals.sqlite3`. Generated outputs are mostly ignored by
Git; tracked source geometry and curated Hidalgo reports remain available after
a fresh clone.

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
1,000 at a time and advances `resultOffset` until a page comes back empty. `scripts/fetch_ml_inputs.py` does this for every
layer listed in its `HCDD1_LAYERS` table and writes GeoJSON to
`data/ml/raw/hcdd1/`; `pipeline/build_layers.py` turns those into the map
overlays:

```bash
uv run --group pipeline python scripts/fetch_ml_inputs.py --only hcdd1
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

**Maintenance and operations**

| Name | Link |
| --- | --- |
| Shredding Operations / Pull-Slope Ditch Maintenance Dashboard | <https://hcdd1.maps.arcgis.com/apps/opsdashboard/index.html#/4ebe2d5ed2e8491e809c4628c77edb02> |
| Dredge/Shred/Spray Ditch Maintenance Dashboard | <https://www.arcgis.com/home/item.html?id=a71ec981d66e46ddb7545098531e4119> |
| M&O Ditch Maintenance Dashboard | <https://www.arcgis.com/home/item.html?id=9e05e9dedc4d40f38b221e20128fe21d> |
| Ditch Inspection Log Map | <https://www.arcgis.com/home/item.html?id=ddbfb541fdcc4767aab3da97bf8a0b3f> |
| Dirt Surplus Map | <https://hcdd1.maps.arcgis.com/apps/webappviewer/index.html?id=b36e99233c7044daa706a2ed368144eb> |
| Illegal Dumping (Experience) | <https://experience.arcgis.com/experience/79e9c3f216e1457aa8a8ea1c3005071f> |

**Other**

| Name | Link |
| --- | --- |
| HCDD1 Right of Way | <https://www.arcgis.com/home/item.html?id=8c66e94ce8cf421fa6a9c18e190e4581> |
| Access Gate Map | <https://www.arcgis.com/home/item.html?id=4b74eaea08f740ccadf508cb3492c9ce> |
| Precinct 4 (map and dashboard) | <https://www.arcgis.com/home/item.html?id=159a19b6223a4901a2fe37d692d01628>, <https://www.arcgis.com/home/item.html?id=66c933d1d85a457bb5aa43529bf7aff8> |
| Survey Request Map | <https://www.arcgis.com/home/item.html?id=7d8c5e5462054f128905cfe6651c596c> |
| Hidalgo County Sanitation Department | <https://www.arcgis.com/home/item.html?id=53697f4296da46aca8f7dd49c24aabbb> |

The district's data terms of use were not found; the overlays here credit
"Hidalgo County Drainage District No. 1". Confirm reuse with the district before
publishing this project outside the course.

## Development and Testing

```bash
uv run pytest
uv run ruff check .
```

Core areas: `src/rgv_flood/` for the app, `pipeline/` for builds, `data/` for
county collections, and `tests/` for verification. Keep source attribution and
source-supplied geometry intact; do not infer live conditions.

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
