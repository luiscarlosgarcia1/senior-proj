/* Hazard, infrastructure, evidence and claims layers: load on first toggle,
 * show/hide on later toggles, and keep the overlay legend in sync. */

import { fetchJson } from "./fetch-json.js";
import { escapeHtml } from "./html.js";
import { LEGENDS, pointStyleFor, styleFor } from "./layer-styles.js";
import { popupHtml } from "./popups.js";

function legendRow(item) {
  if (item.ramp) {
    const cells = item.ramp.map((c) => `<span class="lg lg-ramp" style="background:${c}"></span>`).join("");
    return `<li class="lg-ramp-row"><span class="lg-ramp-cells">${cells}</span>${escapeHtml(item.label)}</li>`;
  }
  // Lines are drawn with a top border, rings with a full border, the rest filled.
  const paint = { line: "border-top-color", dash: "border-top-color", ring: "border-color" }[item.shape] ?? "background";
  return `<li><span class="lg lg-${item.shape}" style="${paint}:${item.color}"></span>${escapeHtml(item.label)}</li>`;
}

function renderLegend() {
  const box = document.getElementById("overlay-legend");
  const rows = [...document.querySelectorAll(".layer-toggle:checked")].flatMap((input) =>
    (LEGENDS[input.value] ?? []).map(legendRow),
  );
  box.hidden = rows.length === 0;
  box.innerHTML = rows.length ? `<ul class="overlay-legend-list">${rows.join("")}</ul>` : "";
}

export function initLayers(map) {
  // ~18k photo points: canvas, not SVG, or panning would crawl.
  const photoCanvas = L.canvas({ pane: "evidence", padding: 0.5 });
  const loaded = new Map(); // layer id -> L.GeoJSON

  function pointToLayer(feature, latlng) {
    const options = { ...pointStyleFor(feature) };
    if (feature.properties?.overlay_type === "flood_photo") {
      options.pane = "evidence";
      options.renderer = photoCanvas;
    }
    return L.circleMarker(latlng, options);
  }

  function onEachFeature(feature, layer) {
    const properties = feature.properties || {};
    const html = popupHtml(properties);
    if (!html) return;
    if (properties.overlay_type === "flood_photo") {
      // Thousands of markers: build the popup on click instead of up front.
      layer.on("click", (e) => L.popup().setLatLng(e.latlng).setContent(html).openOn(map));
    } else {
      layer.bindPopup(html, { maxHeight: 240 });
    }
  }

  async function show(layerId) {
    if (!loaded.has(layerId)) {
      const collection = await fetchJson(`/api/layers/${layerId}.geojson`);
      if (!collection) {
        console.error("layer fetch failed", layerId);
        return;
      }
      loaded.set(layerId, L.geoJSON(collection, { style: styleFor, pointToLayer, onEachFeature }));
    }
    loaded.get(layerId).addTo(map);
  }

  document.querySelectorAll(".layer-toggle").forEach((box) => {
    box.addEventListener("change", (e) => {
      const layerId = e.target.value;
      if (e.target.checked) show(layerId);
      else loaded.get(layerId)?.remove();
      renderLegend();
    });
  });
}
