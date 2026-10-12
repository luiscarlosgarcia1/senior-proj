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
  return (
    `<strong>${esc(p.type)} — ${esc(span)}</strong><br>${esc(p.location)}<br><br>${esc(p.summary)}${record}` +
    `<div class="event-context"><p class="popup-note">Loading gauge readings…</p></div>`
  );
}

/** Bind a popup that, the first time it opens, asks the server what else is
 * known about the event's days: rain at nearby gauges and local reports. */
function bindEventPopup(feature, layer) {
  const properties = feature.properties || {};
  let node = null; // built on first open; kept so the loaded context survives a reopen

  layer.bindPopup(
    () => {
      if (!node) {
        node = document.createElement("div");
        node.innerHTML = eventPopup(properties);
      }
      return node;
    },
    { maxHeight: 320, minWidth: 260 },
  );

  layer.once("popupopen", async (e) => {
    const context = node.querySelector(".event-context");
    const response = await fetch(`/partials/events/${encodeURIComponent(properties.id)}/context`);
    context.outerHTML = response.ok ? await response.text() : "";
    e.popup.update(); // the popup has grown: re-measure and keep it in view
  });
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
          onEachFeature: bindEventPopup,
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

    if (!toggle.checked) {
      toggle.checked = true;
      toggle.dispatchEvent(new Event("change", { bubbles: true })); // so the page address records it
    }
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
