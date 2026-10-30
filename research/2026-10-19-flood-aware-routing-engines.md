# Flood-aware automated rerouting: routing-engine research

**Decision supported:** identify candidates for a later, policy-led selection. This
does not select or procure a provider. Research date: 2026-10-19.

## Bottom line

No reviewed engine makes a flood-susceptibility map or weather forecast into a
road closure. A routing result is therefore safe only when the product supplies
an authoritative, time-bounded **closure / restriction overlay** and rejects a
route that intersects it. Susceptibility and forecast should be inputs to the
separate safety-policy decision; they are not sufficient evidence that a road is
impassable.

The practical managed short-list is **HERE, TomTom, and Mapbox**. HERE is the
strongest documented fit for precise, temporary restrictions because Routing v8
can avoid identified map segments as well as polygons/corridors. TomTom and
Mapbox can avoid coarse areas or snapped points, respectively. Google Routes is
strong for traffic and truck parameters but exposes only feature-level avoid
modifiers, not a project-controlled road-segment overlay. A self-hosted
GraphHopper proof of concept is viable where control and auditability outweigh
operational work; its Apache-2.0 core and custom models make it adaptable, but
the team must own OSM refreshes, dynamic-closure representation, traffic data,
availability, and routing operations.

None of the providers documents flood closures as a complete, authoritative
source for the Rio Grande Valley (RGV). Some traffic products incorporate
incidents/closures, but those feeds must be treated as supplementary signals,
never as a substitute for TxDOT or local-agency closure authority.

## Capability comparison

| Candidate | Current traffic, alternatives, vehicle support | Project-controlled flood restrictions | Commercial / operating model | Fit and limitation |
| --- | --- | --- | --- | --- |
| **HERE Routing API v8** | Real-time traffic; car, truck, pedestrian, bicycle, scooter, bus and taxi. Truck routes accept dimensions and weight constraints. | Avoids polygons, corridors, **specific HERE segment IDs**, and feature categories. | Managed commercial API; confirm contracted quota, retention, cost, SLA, and Texas coverage in procurement. | Best managed candidate to prototype an authoritative edge-level overlay. Requires translating each closure to HERE segment IDs and checking `violatedBlockedRoad` / other route warnings rather than assuming an avoidance request succeeded. |
| **TomTom Routing API** | Uses available current traffic; supports alternatives and car, truck, van, bus, taxi and motorcycle modes. It says closures and road works can affect a route. | `avoidAreas` supports up to ten rectangles; feature avoidance is a preference. No documented caller-supplied road-segment exclusion in this endpoint. | Managed API with a free monthly allowance and enterprise pricing; requests can be batch-calculated. | Good traffic/vehicle comparison candidate, but rectangle overlays are too coarse for a narrow flooded road and do not establish flood authority. |
| **Mapbox Directions** | `driving-traffic` is traffic- and incident-aware; returns up to two alternatives, closure annotations, and has US traffic support. | Can exclude up to 50 snapped custom points, but exclusions are explicitly best-effort and reported as violations when unmet. | Managed, request-billed API (300 RPM documented); assess Navigation terms and production pricing separately. | Useful for a public-facing prototype and route-display integration. Not a responder-grade restriction mechanism: point exclusions can be imprecise and Mapbox exposes no truck profile in Directions. |
| **Google Routes** | `TRAFFIC_AWARE` and `TRAFFIC_AWARE_OPTIMAL`; traffic-aware optimal trades latency for accuracy. Supports alternatives and truck routing with physical constraints. | Avoids tolls, highways, ferries, tunnels and indoor travel only, and those are preferences. | Pay-as-you-go. Traffic-aware routes are Pro SKU; documented limit is 3,000 Compute Routes queries/minute. | Strong general traffic/truck baseline, but unsuitable as the sole engine when the product must impose its own flooded-road restrictions. |
| **GraphHopper (self-hosted core / managed API)** | Core uses OpenStreetMap; custom models can change route weighting. Managed custom profiles are package- and geography-limited. | A custom model can give known road attributes zero or reduced priority, but dynamic closure data needs an owned import/graph update or a dedicated extension; it is not a native flood feed. | Core is Apache-2.0 and can run as a library/server; hosting, OSM imports, updates, traffic feed, monitoring and incident response are the project's responsibility. | Best control/auditability research path, but materially more operations and no built-in real-time traffic comparable to the managed providers. |

## RGV coverage and validation

All candidates can route in the United States or from an OSM extract, but none
of the official material reviewed makes a coverage-quality guarantee for
Cameron, Hidalgo, Starr, and Willacy Counties. Coverage and road restrictions
are data-quality questions, not API feature checkboxes. Before selection, run a
repeatable RGV acceptance suite: urban and rural origins/destinations, farm-to-
market roads, bridges/low-water crossings, truck constraints, known TxDOT
closures, and deliberately blocked roads. Record whether each candidate returns
no route, an alternate route, or a route with a violation.

## Required overlay and automated-update design

1. Ingest authoritative closures and restrictions (TxDOT first; county/municipal
   emergency-management sources only when their ownership and update terms are
   confirmed). Preserve source URL, issued/observed/expiry time, geometry,
   confidence, and an audit trail.
2. Match a closure geometry to each provider's road identifiers where possible;
   retain a buffered polygon as a conservative fallback. Keep **confirmed
   closure**, **unverified report**, **forecast risk**, and **static
   susceptibility** as separate states.
3. Have the safety-policy service decide which state blocks, penalizes, or only
   warns for each public and future responder profile. It must define expiry,
   review, degraded-data behavior, and the response when no safe route exists.
4. Trigger a new route when an applicable restriction changes, when the user
   deviates, and on a bounded ETA/traffic refresh cadence. Validate the returned
   polyline against the active overlay; never silently offer a route that
   intersects a blocking geometry. Display the restriction source and freshness.
5. Keep routing asynchronous from data ingestion: a stale or unavailable
   traffic/vendor response must fail closed for confirmed closures and present
   the user with official guidance, not fabricate a safe route.

This application presently states that it is not for emergency routing. Any
move beyond an educational public prototype needs that product-scope statement,
the safety policy, agency validation, monitoring, and incident procedures
changed together.

## Source notes

- [HERE Routing API v8 — avoidance](https://docs.here.com/routing/docs/routing-v8-avoidance): areas, corridors, features, and HERE segment avoidance.
- [HERE Routing API v8 — truck routing](https://docs.here.com/routing/docs/routing-v8-truck-routing): traffic factors and physical/legal truck restrictions.
- [HERE Routing API v8 reference](https://docs.here.com/routing/reference/routing-api-v8-calculateroutes): returned route violations including blocked roads.
- [TomTom Calculate Route](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route): traffic, closures/road works, alternatives, modes, and rectangle avoidance.
- [TomTom routing product information](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/product-information/introduction) and [pricing](https://docs.tomtom.com/pricing): batching and usage plans.
- [Mapbox Directions API](https://docs.mapbox.com/api/navigation/directions/): traffic profile, closures, alternatives, custom point exclusions, limits, and billing unit.
- [Google Routes traffic settings](https://developers.google.com/maps/documentation/routes/config_trade_offs), [route modifiers](https://developers.google.com/maps/documentation/routes/route-modifiers), [vehicle types](https://developers.google.com/maps/documentation/routes/vehicles), and [usage/billing](https://developers.google.com/maps/documentation/routes/usage-and-billing): traffic behavior, avoid scope, truck support, limits, and pricing model.
- [GraphHopper core repository](https://github.com/graphhopper/graphhopper) and [custom models / profiles](https://docs.graphhopper.com/openapi/section/explore-our-apis/api-explorer): Apache-2.0 self-hosted core, OSM support, and custom routing behavior.
- [Project scope statement](../../README.md): current system is educational/comparative only and not for emergency routing.
