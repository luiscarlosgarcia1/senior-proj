/* RGV Flood Impact Visualizer: Leaflet map entry point.
 *
 * The map owns spatial state (pan/zoom, which overlays are visible). HTMX owns
 * the server-rendered side panels (source metadata, event list, reports).
 */

import { initAddressSearch } from "./address-search.js";
import { initEventsLayer } from "./events-layer.js";
import { initLayers } from "./layers.js";
import { initLiveSignals } from "./live-signals.js";
import { initAccordion, initCountySelect } from "./sidebar.js";

const config = window.RGV_CONFIG;
const map = L.map("map").setView(config.center, config.zoom);

// The map container is sized by flexbox; measure it once layout has settled.
requestAnimationFrame(() => map.invalidateSize());
window.addEventListener("load", () => map.invalidateSize());

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

// Stacking is fixed by pane, not by the order layers are toggled in. Hazard and
// infrastructure layers use Leaflet's overlay pane (400).
const PANE_Z_INDEX = { evidence: 430, signals: 460, events: 480 };
for (const [name, zIndex] of Object.entries(PANE_Z_INDEX)) map.createPane(name).style.zIndex = zIndex;

initLayers(map);
initEventsLayer(map);
initAddressSearch(map);
initAccordion();
initCountySelect(map, config);
initLiveSignals(map).catch((error) => console.error("live signal fetch failed", error));
