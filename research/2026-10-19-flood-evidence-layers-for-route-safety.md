# Flood evidence layers for automated route safety

**Research question:** Which public layers should feed automated flood-aware
route safety for Cameron, Hidalgo, Starr, and Willacy Counties, and what role
should each play?

**Decision:** Use a source-ranked model. An official, current road closure is
the only evidence in this set that can automatically make a matched road edge
unusable. Current official flood alerts and hydrologic observations/forecasts
can increase risk (and, after a separately approved conservative policy,
trigger avoidance), but neither identifies every impassable road. FEMA, TWDB,
topography, and the proposed susceptibility model are context/prior-risk data;
they must not independently exclude a road.

## Recommended evidence hierarchy

| Rank and layer | Resolution, coverage, freshness | Access and provenance | Route role |
| --- | --- | --- | --- |
| 1. **TxDOT DriveTexas current road-condition points and lines** | Feature geometry is a point or line; current records can include `Flooding` and `Closed`. The repository already queries both official public FeatureServer layers, restricted to TxDOT county numbers 31 (Cameron), 108 (Hidalgo), 214 (Starr), and 245 (Willacy). TxDOT's documented polling limit used by the existing pipeline is 15 minutes. | Public ArcGIS FeatureServer published by TxDOT; preserve its geometry, condition, effective/expiry times, and source identity. The existing adapters identify the endpoints and condition codes in [`pipeline/drivetexas.py`](../../pipeline/drivetexas.py) and enforce the 15-minute minimum in [`pipeline/run_drivetexas.py`](../../pipeline/run_drivetexas.py). | **Direct exclusion only when** the record is an active official closure/flooding condition and its geometry can be conservatively matched to a road edge. Do not infer closure from nearby geometry, stale records, a point that cannot be matched, or an unknown condition. Display unmatched records. |
| 2. **NWS active flood/flash-flood/coastal-flood alerts** | Alert polygons, county/zone references, or occasionally no geometry; they cover the four counties when issued for their affected areas. Their validity is event-driven, so poll rather than assume a fixed publication schedule. | The free, public NWS API exposes active alerts and their CAP content; it is explicitly intended for redistributing alerts and decision-support tools ([NWS Alerts Web Service](https://www.weather.gov/documentation/services-web-alerts)). The API is cache-friendly and has non-public but reasonable rate limits ([NWS API](https://www.weather.gov/documentation/services-web-api)). | **Risk increase / trigger for a stricter mode**, not automatic street closure. A warning polygon is a warning area, not a surveyed road-flood footprint. Keep as visible official context when no geometry is supplied. |
| 3. **NWS National Water Prediction Service (NWPS) gauge observations and official forecasts** | Station/gauge locations plus observed and forecast stage/flow series; coverage is only at available gauges/reaches, not continuous road coverage. The NWPS API supports gauge discovery and observed/forecast stage-flow products ([NWPS API specification](https://api.water.noaa.gov/nwps/v1/docs/)). | Free NWS/NOAA API. It supplies the data behind NWPS: official streamflow forecasts, observations, flood categories and impacts ([NOAA API information](https://api.water.noaa.gov/about/api)). | **Risk increase / display context.** Map a gauge's forecast threshold/impact to a defined nearby drainage corridor only after validating the local relation; it cannot close arbitrary nearby streets. Prefer official forecasts over model-only guidance. |
| 4. **USGS real-time streamgage observations** | Point measurements; readings are usually made every 15 minutes and transmitted hourly ([USGS Instantaneous Values](https://waterservices.usgs.gov/docs/instantaneous-values/)). Availability is station-specific, so inventory sites and parameters within/near the four counties before relying on it. Values are provisional and can be revised. | Free USGS Water Services. The current continuous-data API can return the latest value for each time series ([USGS latest-continuous endpoint](https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous?f=html)). | **Risk increase / corroboration**, especially where an observed stage/discharge crosses a locally validated threshold. It is not road geometry and cannot alone exclude a road. |
| 5. **NWS weather forecasts, observations, and forecast alerts** | NWS point lookup provides hourly and 12-hour forecasts for the next seven days ([NWS API](https://www.weather.gov/documentation/services-web-api)). The NDFD CONUS grid is 2.5 km (hourly for days 1–3 in the cited service guidance) ([NDFD use guidelines](https://graphical.weather.gov/xml/mdl/XML/Design/WebServicesUseGuidelines.php)); NWS policy sets at least daily updates, while actual updates are event/office dependent ([NDFD directive](https://www.weather.gov/media/directives/010_pdfs_archived/pd01002001d.pdf)). Station observations may normally be delayed about 20 minutes by upstream quality control ([NWS API known issues](https://www.weather.gov/documentation/services-web-api)). All four counties are within CONUS coverage. | Free NWS public API; obtain point-specific endpoints through `/points/{lat},{lon}`, and periodically refresh that mapping because the office/grid can change. | **Risk increase / predictive context.** Use forecast precipitation, severe-weather signals and active flood alerts to raise route risk or request a new route; no weather grid is proof a particular road is flooded. |
| 6. **FEMA National Flood Hazard Layer (NFHL)** | Polygonal effective flood-map data, not a live inundation feed. FEMA describes NFHL as a geospatial database of effective flood maps; its Map Service Center is the official source ([FEMA flood products](https://www.fema.gov/flood-maps/products-tools)). Digital coverage is incomplete. In this project it covers Cameron, Starr, and Willacy; Hidalgo instead has a legacy 1981 HCDD1 digitized FIRM ([seed-data provenance](../../data/seed/README.md)). | Public FEMA GIS/Map Service Center data; update only when FEMA publishes a new effective map/LOMC, not on an operational cadence. | **Static susceptibility/context only.** It can weight a road segment's baseline exposure, explain an avoidance recommendation, and inform emergency planning. It cannot assert present road flooding. |
| 7. **TWDB 2025 Cursory Floodplain Dataset / Floodplain Quilt** | Statewide, 3-m flood-hazard rasters for 20%, 10%, 1%, and 0.2% annual-chance events; therefore all four counties are covered. TWDB calls the data complete but approximate, developed from statewide 2-D hydrodynamic modeling ([TWDB 2025 data update](https://www.twdb.texas.gov/flood/planning/planningdocu/2028/doc/2025_07_15_Newsletter.pdf)). The dataset represents scenario probabilities, not an event-time timestamp. | Public TWDB Flood Planning Data Hub. TWDB's review says it is a rapid-assessment gap-filler and not equivalent to conventional engineering studies ([TWDB independent review](https://www.twdb.texas.gov/flood/science/doc/Cursory-Floodplain-Review-Final-Report.pdf)). The repository currently serves 1% and 0.2% excerpts from the 2025 dataset. | **Static susceptibility/context only.** Use for baseline routing cost and coverage gaps, never road exclusion. Its model can miss or misrepresent drainage, roads, levees, dams, and local terrain effects. |
| 8. **Local topography, drainage infrastructure, and a future flood-susceptibility model** | Resolution and update cadence depend on the chosen source/model. The repository's planned Hidalgo model inputs include elevation, land cover, soils, Atlas 14 rainfall, roads/buildings, insurance, and drainage-district layers; it is not currently an operational layer ([project README](../../README.md)). | Derived/project data rather than an official current closure feed. Its training, validation, uncertainty, spatial transferability and refresh procedure would need a separate decision. | **Baseline risk only, initially display-only.** It may eventually adjust route cost after validation, but must not independently declare a road impassable. |

## Why susceptibility alone cannot automate avoidance

Susceptibility expresses the chance or modeled extent for an assumed event, not
whether a specific road is flooded, open, or passable now. The gap is especially
important here:

- FEMA NFHL is effective regulatory-map data, with incomplete digital coverage;
  it is not real-time inundation.
- TWDB explicitly characterizes its statewide 3-m product as approximate,
  rapid-assessment data. Its independent review says it should not be solely
  relied on for quantified risk assessment; roads, drainage, levees, dams and
  embankments are among the kinds of constructed features that can alter flow.
- A susceptibility score has neither an observation time nor a road-status
  authority. Automatically blocking every road in a 1%-annual-chance polygon
  would create broad false closures, while blocking none during a flash flood
  would create false safety.

The safe default is therefore: **official matched road closure > current official
hazard evidence > hydrologic/weather risk > static susceptibility/context**.
Only the first category changes route feasibility. The other categories should
make the route engine prefer lower-risk alternatives or return an explicit
uncertainty warning under a policy that remains to be decided.

## Operational implications for the next decision

1. Keep the existing 15-minute scheduler as an upper bound for the current
   DriveTexas snapshot; the UI already treats live signals as fresh for 30
   minutes ([live-signals endpoint](../../src/rgv_flood/api/live_signals.py)).
   Routing must define a stricter maximum age and fail-safe behavior for a
   missed or incomplete snapshot rather than silently treating stale data as
   clear roads.
2. Poll NWS alert and weather products with HTTP cache semantics and source
   expiry; do not invent a cadence where NWS publishes event-driven changes.
   Review the NWS terms/rate limits and identify the service with a meaningful
   `User-Agent` before production traffic.
3. Before a hydrologic signal affects routing, inventory the actual NWPS and
   USGS gauges/reaches serving these counties and validate each threshold and
   affected road/drainage relationship with the responsible local agency.
4. Retain source timestamps, provenance, geometry, validity intervals and the
   exact policy decision behind every reroute. The current project already
   preserves DriveTexas source geometry and attributes rather than inferring
   coverage; that conservative approach should remain.

## Scope and limitations

This is a data-layer recommendation, not authorization to operate a public or
emergency dispatch system. It does not establish vehicle-specific passability,
agency operating procedures, or a routing safety threshold. Those are the
next policy/validation decisions. No ingestion or routing behavior was changed.
