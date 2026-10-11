/* Active official signals (NWS alerts, DriveTexas closures, Hidalgo notices).
 *
 * The server sends only active, official signals that carry source-supplied
 * geometry; unmappable notices stay in the sidebar as links.
 */

import { escapeHtml as esc } from "./html.js";

function signalStyle(feature) {
  const source = feature.properties?.source || "";
  if (source.startsWith("drivetexas:")) return { color: "#9a3412", weight: 4 };
  return { color: "#7c3aed", weight: 2, fillColor: "#a78bfa", fillOpacity: 0.2 };
}

function signalPopup(p) {
  const retrieved = p.retrieved_at ? `<br>Retrieved ${esc(p.retrieved_at)}` : "";
  const source = p.source_url ? ` <a href="${esc(p.source_url)}" target="_blank" rel="noopener">Source</a>` : "";
  return `<strong>${esc(p.summary)}</strong><br>${esc(p.source_publisher)}${retrieved}${source}`;
}

export async function initLiveSignals(map) {
  const response = await fetch("/api/live-signals.geojson");
  if (!response.ok) return;
  L.geoJSON(await response.json(), {
    pane: "signals",
    style: signalStyle,
    pointToLayer: (feature, latlng) =>
      L.circleMarker(latlng, { ...signalStyle(feature), pane: "signals", radius: 7, fillOpacity: 0.75 }),
    onEachFeature: (feature, layer) => layer.bindPopup(signalPopup(feature.properties || {})),
  }).addTo(map);
}
