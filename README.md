# RGV Flood Impact Visualizer

CSCI 4390 Senior Project — Danny McClain, Luis Garcia. Faculty adviser: Sergei Chuprov.

A browser map that compares **best-available flood-hazard information** across the
four Lower Rio Grande Valley counties — **Cameron, Hidalgo, Starr, Willacy** — and
shows separately labeled **historical** road-closure reports collected from local
news coverage.

> Educational and comparative only. Not for flood-insurance, emergency-routing, or
> engineering decisions. It does not compute flood depth, predict active flooding,
> or certify a property's flood zone. Historical news reports are not live closures.

## Stack

- **Backend:** Flask + `jinja-partials`
- **Frontend:** server-rendered HTML with HTMX for side panels; Leaflet for the map
- **Pipeline:** Python (`geopandas`, `shapely`, `pyproj`) for spatial prep;
  `requests` + `beautifulsoup4` for news collection — runs offline, not shipped

## Data sources

| County | Preferred hazard layer |
| --- | --- |
| Cameron, Starr, Willacy | FEMA National Flood Hazard Layer (NFHL) |
| Hidalgo | Hidalgo County Drainage District No. 1 digitized 1981 map (no FEMA digital data) |
| all four | TWDB 2025 cursory floodplain dataset (modeled, contextual) |
| baseline | US Census TIGER/Line county boundaries |

## Develop

```bash
uv sync                      # app deps only
uv sync --group dev          # + pytest, ruff
uv sync --group pipeline     # + geospatial + scraping libs (for pipeline/)
```

Run the app:

```bash
uv run flask --app rgv_flood run --debug
```

Test / lint:

```bash
uv run pytest
uv run ruff check .
```

Build the map data (the generated files are gitignored — run this after a clone):

```bash
uv run --group pipeline python pipeline/build_layers.py   # hazard layers (~90s)
uv run python pipeline/build_events.py                    # flood events, reports, rainfall
```

## Layout

```
src/rgv_flood/        Flask app (factory, config, views, templates, static)
  severity.py         the ONLY place source categories become a relative class
  static/data/        pipeline outputs the app serves as-is
pipeline/             offline data engineering (see pipeline/README.md)
data/                 raw + intermediate source data and acquisition notes
tests/
```
