# Seed data

The only data files in this repository. Everything else the project uses is
downloaded by the build and written straight into the central database
(`data/generated/rgv-flood.sqlite3`); see [pipeline/README.md](../../pipeline/README.md).

These files are here because no publisher offers them as a simple scripted
download: the flood-hazard geometry was assembled and clipped per county by
hand-run scripts in an earlier phase of the project, and the public reports were
curated by hand. The build reads them into memory and never changes them. The
running app never reads them at all.

## Per-county geometry

One folder per county (`cameron/`, `hidalgo/`, `starr/`, `willacy/`).

| File | Publisher | Dataset | Status | Vintage |
| --- | --- | --- | --- | --- |
| `boundary.geojson` | U.S. Census Bureau | TIGER/Line 2023 counties | reference | 2023 |
| `fema-nfhl.geojson` (Cameron, Starr, Willacy) | Federal Emergency Management Agency | National Flood Hazard Layer, MapServer layer 28 (Flood Hazard Zones) | official, effective | effective FIRM date varies by panel |
| `hcdd1-firm-1981.geojson` (Hidalgo only) | Hidalgo County Drainage District No. 1 | FloodMapService/FeatureServer/0, a digitized copy of the 1981 FIRM | legacy local reference | 1981 base map; some zones revised by later LOMR |
| `twdb-cursory-1in100.geojson`, `twdb-cursory-1in500.geojson` | Texas Water Development Board | 2025 Cursory Floodplain Dataset (Fathom 3 m), Region 15, clipped to the county | modeled, contextual | 2025 |

Notes:

- FEMA has no digital NFHL coverage for Hidalgo County, so the drainage
  district's digitized 1981 FIRM is the only flood-zone map there. Its zone
  letters are not confirmed equivalent to current FEMA classes.
- The FEMA layers were downloaded by bounding box, so a few polygons from
  neighboring counties spill in. `build_layers.py` clips them to the boundary.
- The TWDB layers are modeled estimates, not effective FEMA maps or regulatory
  determinations.
- Everything is EPSG:4326 except `boundary.geojson`, which is EPSG:4269 as
  delivered by TIGER.

| County | FEMA NFHL / FIRM features | TWDB 1-in-100 | TWDB 1-in-500 |
| --- | --- | --- | --- |
| Cameron | 1,643 | 4,147 | 2,302 |
| Hidalgo | 143 (1981 FIRM) | 6,831 | 3,786 |
| Starr | 307 | 3,505 | 2,467 |
| Willacy | 382 | 2,402 | 986 |

## NFIP policies by year

`nfip-policies-by-year.csv` (`county,year,policies`) counts the National Flood
Insurance Program policies in force in each county and year, 2009 on, from
FEMA's "FIMA NFIP Redacted Policies v2" dataset
(<https://www.fema.gov/api/open/v2/FimaNfipPolicies>). A policy counts toward
the year its term began. FEMA retired that dataset on 2026-10-15 and its
replacement cannot be filtered by county, so the counts are kept here.
`pipeline/seed_nfip_policies.py` regenerates the file from a saved copy of the
export. 2026 is a partial year.

## Curated public reports

`hidalgo/public-reports.ndjson` holds 16 local-news and local-government flood
reports, one JSON record per line, collected by hand on 2026-09-04 from Hidalgo
County, the City of McAllen and KRGV Channel 5 News. They were found by
searching the public web around NOAA event dates, municipalities, streets,
closures and drainage locations. Each has a public original URL, a source date
and a Hidalgo County location; geometry is null where the source publishes no
coordinate. No social-media post was kept, because none could be verified
without bypassing an access restriction.

Reports about the same flood share a `duplicate_group_id`:

| Group | Event window | What it covers |
| --- | --- | --- |
| `hidalgo-flood-2018-06` | 2018-06-20 to 2018-06-21 | June 2018 flooding and recovery |
| `hidalgo-flood-2020-hanna` | 2020-07-25 to 2020-07-31 | Hurricane Hanna impact and response |
| `hidalgo-flood-2021-05` | 2021-05-19 | Weslaco street flooding |

To add reports for another county, create `<county>/public-reports.ndjson` with
records of the same shape; `build_events.py` picks it up on the next build.
