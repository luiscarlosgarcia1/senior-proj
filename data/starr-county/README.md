# Starr County dataset

This directory is the shared collection for Starr County data acquisition. It
covers 1 January 2000 through the present and mirrors the layout of
`data/hidalgo-county/`. It is a collection scaffold, not a prediction dataset and
not a statement that every retained claim is true.

## Layout

- `manifest.json` defines scope, source-family directories, and the collection policy.
- `schemas/` contains the validation contracts for the two record classes.
- `records/events-and-public-reports/` holds one JSON object per line for documented
  flood events and supplementary public reports.
- `records/layers-and-weather/` holds one JSON object per line for static/reference
  layers and weather-observation datasets.
- `sources/` holds source-specific acquisition notes, grouped by source family.
- `flood-hazard-layers/` holds map-ready GeoJSON (FEMA NFHL or the Hidalgo legacy
  FIRM, TWDB modeled extent, and the county boundary) imported from the earlier
  Flood Project working directory. See `flood-hazard-layers/manifest.json`.

## Collection rules

Validate each line in `records/events-and-public-reports/` against
`schemas/event-public-report.schema.json`, and each line in
`records/layers-and-weather/` against `schemas/layer-weather-observation.schema.json`.
Preserve the original source reference and stated precision. Use `unknown` or `null`
where appropriate; do not infer a coordinate, event extent, or timestamp.

Public social material must be public, accessible through permitted collection methods,
and limited to what is necessary for this project. Do not collect private material or
bypass platform access controls.
