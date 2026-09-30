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

The Flask app reads precomputed layers and summaries from
`src/rgv_flood/static/data/`. Live-source snapshots are separate in
`data/generated/live-signals.sqlite3`. Generated outputs are mostly ignored by
Git; tracked source geometry and curated Hidalgo reports remain available after
a fresh clone.

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
