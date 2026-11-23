---
name: rain_vs_claims
use_when: Comparing yearly rainfall with flood claims or flood events in a county, or whether wet years brought more flooding.
tools: [find_place, rain_vs_claims, claims_summary, query_database]
tables: [rainfall_station_years, weather_stations, nfip_claims, flood_events]
---
## How to answer
1. Call rain_vs_claims with the county and years. It is county-level only; for a town, find its county with find_place and say you used the county.
2. Point out the years that stand out: the wettest, and the ones with the most claims or events. Say whether they line up.
3. If a year shows no rain value, say no gauge had a complete record that year; do not treat it as dry.

## Traps
- Rain is the average over the county's gauges that reported on at least 330 days of the year. Fewer days would make missing days look dry.
- Rain values are already in inches. Never convert them again.
- A year's total can hide one huge storm: a dry year can still have a damaging flood day.
- Rainfall and claims moving together is not proof that one caused the other. Say "lined up with", not "caused".

## Good answer
In Cameron County the wettest years were also the years with the most flood claims.
- 2008: 41.2 inches of rain, 1,104 claims, 6 NOAA flood events.
- 2015: 38.7 inches, 312 claims, 9 events.
- 2011 was the driest (12.1 inches), with 3 claims.
From: rainfall_station_years (complete gauge-years only), nfip_claims, flood_events; Cameron County; 2006-2015
Limits: rain is a county average of a few gauges, and claims count only insured buildings.

(The figures above only show the shape. Every real figure must come from a tool result.)
