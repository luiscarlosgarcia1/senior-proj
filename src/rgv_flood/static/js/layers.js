/* Hazard, infrastructure, evidence and claims layers: load on first toggle,
 * show/hide on later toggles, and keep the overlay legend in sync. A layer
 * listed in LAYER_PARTS also gets a checkbox per part under its own. */

import { fetchJson } from "./fetch-json.js";
import { escapeHtml } from "./html.js";
import { LAYER_PARTS, LEGENDS, pointStyleFor, styleFor } from "./layer-styles.js";
import { PHOTO_WIDTH, popupHtml } from "./popups.js";

function legendRow(item) {
  if (item.ramp) {
    const cells = item.ramp.map((c) => `<span class="lg lg-ramp" style="background:${c}"></span>`).join("");
    return `<li class="lg-ramp-row"><span class="lg-ramp-cells">${cells}</span>${escapeHtml(item.label)}</li>`;
  }
  // Lines are drawn with a top border, rings with a full border, the rest filled.
  const paint = { line: "border-top-color", dash: "border-top-color", ring: "border-color" }[item.shape] ?? "background";
  return `<li><span class="lg lg-${item.shape}" style="${paint}:${item.color}"></span>${escapeHtml(item.label)}</li>`;
}

/** The part checkboxes of one layer. */
const partBoxes = (layerId) => [...document.querySelectorAll(`.layer-part[data-layer="${layerId}"]`)];

function renderLegend() {
  const box = document.getElementById("overlay-legend");
  const rows = [...document.querySelectorAll(".layer-toggle:checked")].flatMap((input) => {
    const hidden = new Set(partBoxes(input.value).filter((part) => !part.checked).map((part) => part.value));
    return (LEGENDS[input.value] ?? []).filter((item) => !hidden.has(item.part)).map(legendRow);
  });
  box.hidden = rows.length === 0;
  box.innerHTML = rows.length ? `<ul class="overlay-legend-list">${rows.join("")}</ul>` : "";
}

/** A checkbox per part, under the layer's row; shown while the layer is on. */
function addPartControls(box) {
  const parts = LAYER_PARTS[box.value];
  if (!parts) return;
  const list = document.createElement("ul");
  list.className = "layer-parts";
  list.hidden = !box.checked;
  list.innerHTML = parts
    .map(
      (part) => `<li><label class="layer-toggle-label">
        <input type="checkbox" class="layer-part" data-layer="${escapeHtml(box.value)}" value="${escapeHtml(part.id)}" checked>
        <span>${escapeHtml(part.label)}</span></label></li>`,
    )
    .join("");
  box.closest(".layer-row").append(list);
}

export function initLayers(map) {
  // ~18k photo points: canvas, not SVG, or panning would crawl.
  const photoCanvas = L.canvas({ pane: "evidence", padding: 0.5 });
  const loaded = new Map(); // layer id -> promise of {group, parts: Map(part id -> L.GeoJSON)}

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
    if (properties.overlay_type === "fema_photos") {
      layer.bindPopup(html, { minWidth: PHOTO_WIDTH, maxWidth: PHOTO_WIDTH + 40 });
    } else if (properties.overlay_type === "flood_photo") {
      // Thousands of markers: build the popup on click instead of up front.
      layer.on("click", (e) => L.popup({ minWidth: PHOTO_WIDTH }).setLatLng(e.latlng).setContent(html).openOn(map));
    } else {
      layer.bindPopup(html, { maxHeight: 240 });
    }
  }

  const geoJson = (collection, filter) => L.geoJSON(collection, { style: styleFor, pointToLayer, onEachFeature, filter });

  /** One Leaflet layer per part, or a single one for a layer without parts. */
  function build(layerId, collection) {
    const parts = new Map();
    for (const part of LAYER_PARTS[layerId] ?? []) {
      parts.set(part.id, geoJson(collection, (feature) => part.includes(feature.properties || {})));
    }
    const group = parts.size ? L.layerGroup() : geoJson(collection);
    return { group, parts };
  }

  /** Put the checked parts in the group, the first-listed last so it is drawn on top. */
  function showParts(layerId, { group, parts }) {
    group.clearLayers();
    for (const box of partBoxes(layerId).reverse()) {
      if (box.checked) group.addLayer(parts.get(box.value));
    }
  }

  /** The layer's Leaflet layers, fetched once (null if the request failed).
   * Its sidebar row shows a spinner while the download is in flight. */
  function layerFor(box) {
    const layerId = box.value;
    if (!loaded.has(layerId)) {
      const row = box.closest(".layer-row");
      row.classList.remove("failed");
      row.classList.add("loading");
      const pending = fetchJson(`/api/layers/${layerId}.geojson`)
        .catch(() => null)
        .then((collection) => {
          row.classList.remove("loading");
          if (collection) return build(layerId, collection);
          console.error("layer fetch failed", layerId);
          row.classList.add("failed");
          loaded.delete(layerId); // let the next toggle try again
          return null;
        });
      loaded.set(layerId, pending);
    }
    return loaded.get(layerId);
  }

  async function sync(box) {
    const layer = await layerFor(box);
    if (!layer) {
      box.checked = false;
      renderLegend();
      return;
    }
    if (layer.parts.size) showParts(box.value, layer);
    // Checked against the box as it is now: it may have been toggled again while loading.
    if (box.checked) layer.group.addTo(map);
    else layer.group.remove();
  }

  document.querySelectorAll(".layer-toggle").forEach((box) => {
    addPartControls(box);
    box.addEventListener("change", () => {
      const parts = box.closest(".layer-row").querySelector(".layer-parts");
      if (parts) parts.hidden = !box.checked;
      // An unchecked layer that was never fetched has nothing to remove.
      if (box.checked || loaded.has(box.value)) sync(box);
      renderLegend();
    });
  });

  document.querySelectorAll(".layer-part").forEach((part) => {
    part.addEventListener("change", async () => {
      renderLegend();
      const layer = loaded.has(part.dataset.layer) ? await loaded.get(part.dataset.layer) : null;
      if (layer) showParts(part.dataset.layer, layer);
    });
  });
}
