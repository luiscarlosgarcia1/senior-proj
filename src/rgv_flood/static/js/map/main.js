/* The map: MapLibre on an OpenStreetMap vector basemap (OpenFreeMap by
 * default; the style URLs are settings). Light and dark swap the basemap and
 * recolor our layers; county changes fit the map to the county and emphasize
 * its outline. Basemap labels show on the US side only. Other modules get the
 * map from `mapReady`. */

import * as maplibregl from "../../vendor/maplibre/maplibre-gl.mjs";
import { getJson } from "../api.js";
import { hideForeignLabels, usSideMask } from "./labels.js";
import { beginStyleSwitch, loadedData, ownStyle } from "./layers.js";

const VALLEY = [[-99.2, 25.8], [-97.1, 26.8]]; // west-south, east-north of the four counties
const container = document.getElementById("map");

const basemapFor = (theme) => container.dataset[theme === "light" ? "basemapLight" : "basemapDark"];
const currentTheme = () => document.documentElement.dataset.theme || "light";

let labelMask = null; // set once the county outlines arrive

/** Limit the basemap's land labels to the US side (see labels.js). */
async function hideLabelsInMexico(map) {
  try {
    labelMask = usSideMask(await getJson("layers/county-boundaries.geojson", {}, { cancelPrevious: false }));
  } catch (error) {
    console.warn("county outlines unavailable; basemap labels left as they are", error);
    return;
  }
  const before = map.getStyle().layers;
  hideForeignLabels(before, labelMask).forEach((layer, i) => {
    if (layer !== before[i]) map.setFilter(layer.id, layer.filter);
  });
}

let resolveReady;
/** Resolves with the map once its first style has loaded. */
export const mapReady = new Promise((resolve) => {
  resolveReady = resolve;
});

function createMap() {
  const map = new maplibregl.Map({
    container,
    style: basemapFor(currentTheme()),
    bounds: VALLEY,
    fitBoundsOptions: { padding: 20 },
    minZoom: 7,
    maxZoom: 17,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
  map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");
  map.once("load", () => {
    resolveReady(map);
    hideLabelsInMexico(map);
  });
  if (new URLSearchParams(location.search).has("test")) window.__rgvMap = map;
  return map;
}

/** Swap the basemap for the theme; our layers come back from memory in the new colors. */
function applyTheme(map, theme) {
  beginStyleSwitch(map);
  map.setStyle(basemapFor(theme), {
    diff: false,
    transformStyle: (_previous, next) => {
      const own = ownStyle();
      const basemap = labelMask ? hideForeignLabels(next.layers, labelMask) : next.layers;
      return { ...next, sources: { ...next.sources, ...own.sources }, layers: [...basemap, ...own.layers] };
    },
  });
}

const titleCase = (slug) => slug.charAt(0).toUpperCase() + slug.slice(1);

/** Fit the map to a county (or the whole valley) and emphasize its outline. */
function showCounty(map, slug) {
  const name = slug ? titleCase(slug) : null;
  const outline = "lyr-county-boundaries-line";
  if (map.getLayer(outline)) {
    map.setPaintProperty(outline, "line-width", name ? ["case", ["==", ["get", "county"], name], 2.6, 0.8] : 1.2);
  }
  const feature = name && loadedData("county-boundaries")?.features.find((f) => f.properties.county === name);
  if (!feature) {
    map.fitBounds(VALLEY, { padding: 20, duration: 600 });
    return;
  }
  const bounds = new maplibregl.LngLatBounds();
  for (const ring of feature.geometry.type === "Polygon" ? feature.geometry.coordinates : feature.geometry.coordinates.flat()) {
    for (const point of ring) bounds.extend(point);
  }
  map.fitBounds(bounds, { padding: 30, duration: 600 });
}

if (container) {
  const map = createMap();
  window.addEventListener("rgv:theme", (event) => applyTheme(map, event.detail));
  window.addEventListener("rgv:county", (event) => showCounty(map, event.detail));
  window.addEventListener("rgv:map-shown", () => requestAnimationFrame(() => map.resize())); // phones: map view again
}

export { maplibregl };
