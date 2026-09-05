# Preprocessing pipeline

Offline data engineering. Run during development; **not** shipped with the app.
Outputs land in `src/rgv_flood/static/data/` as map-ready GeoJSON plus
`layers.json` (layer manifest) and `closures.json` (reviewed road-closure reports).

Install deps:

```bash
uv sync --group pipeline
```

## Stages

| Script | Input | Output |
| --- | --- | --- |
| `ingest_tiger.py` | US Census TIGER county shapefiles | `county-boundaries.geojson` |
| `ingest_fema_nfhl.py` | FEMA NFHL (Cameron, Starr, Willacy) | `fema-nfhl.geojson` |
| `ingest_hidalgo_dd1.py` | Hidalgo County DD No. 1 digitized 1981 map | `hidalgo-dd1-1981.geojson` |
| `ingest_twdb.py` | TWDB 2025 cursory floodplain dataset | `twdb-cursory.geojson` |
| `scrape_closures.py` | selected local-news article pages | `closures_candidates.json` (needs manual review) |
| `build_layers.py` | the above | `layers.json` manifest |

## Rules

- Reproject everything to EPSG:4326.
- Simplify geometry only where visual meaning is retained; record the tolerance.
- Every feature keeps `source`, `original_category`, and (where the mapping table
  in `rgv_flood/severity.py` allows) `relative_class`.
- `scrape_closures.py` respects each site's robots rules and rate limits, caches
  only needed metadata, and never writes straight to `closures.json` — a human
  promotes reviewed rows.
