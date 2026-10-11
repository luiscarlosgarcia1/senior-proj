/* Documented flood events (NOAA Storm Events points), toggled from the sidebar
 * and flown to when a locatable row in the event list is clicked. */

import { fetchJson } from "./fetch-json.js";
import { escapeHtml as esc } from "./html.js";

const MARKER = { pane: "events", radius: 5, color: "#854d0e", weight: 1, fillColor: "#eab308", fillOpacity: 0.85 };

function eventPopup(p) {
  const span = p.date_end && p.date_end !== p.date ? `${p.date} – ${p.date_end}` : p.date;
  const record = p.source_url
    ? `<br><br><a href="${esc(p.source_url)}" target="_blank" rel="noopener">NOAA Storm Events record</a>`
    : "";
  return `<strong>${esc(p.type)} — ${esc(span)}</strong><br>${esc(p.location)}<br><br>${esc(p.summary)}${record}`;
}

export function initEventsLayer(map) {
  const toggle = document.getElementById("events-toggle");
  let layerPromise = null;

  /** The events layer, fetched once on first use (null if the request failed). */
  function eventsLayer() {
    layerPromise ??= fetchJson("/api/flood-events.geojson").then(
      (collection) =>
        collection &&
        L.geoJSON(collection, {
          pointToLayer: (_feature, latlng) => L.circleMarker(latlng, MARKER),
          onEachFeature: (feature, layer) => layer.bindPopup(eventPopup(feature.properties || {}), { maxHeight: 220 }),
        }),
    );
    return layerPromise;
  }

  async function setVisible(visible) {
    const layer = await eventsLayer();
    if (!layer) return;
    if (visible) layer.addTo(map);
    else layer.remove();
  }

  toggle.addEventListener("change", (e) => setVisible(e.target.checked));

  // Clicking a locatable list row shows the layer, flies there and opens its popup.
  document.addEventListener("click", async (e) => {
    const row = e.target.closest(".event-item.locatable");
    if (!row) return;
    const lat = parseFloat(row.dataset.lat);
    const lon = parseFloat(row.dataset.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;

    toggle.checked = true;
    await setVisible(true);
    map.flyTo([lat, lon], 13);
    map.once("moveend", async () => {
      const layer = await eventsLayer();
      layer?.eachLayer((marker) => {
        if (marker.feature?.properties?.id === row.dataset.id) marker.openPopup();
      });
    });
  });
}
