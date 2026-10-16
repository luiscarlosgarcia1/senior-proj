/* Puts layers on the map, shows and hides them, and keeps them across theme
 * switches.
 *
 * Every layer the reader turns on is downloaded once and kept in `registry`
 * (its source spec, with GeoJSON data held in memory, and its info). The map
 * itself can be rebuilt from the registry at any time, which is what a theme
 * switch does: the basemap changes, our sources and style layers are re-added
 * from memory with the new theme's colors, and nothing is downloaded again. */

import { getJson } from "../api.js";
import { readColors, styleLayersFor } from "./styles.js";

const registry = new Map(); // layer id -> { info, source, visible, partsOff: Set }
const loading = new Map(); // layer id -> Promise of its source spec

/** Where the layer's data comes from: tiles for big layers, GeoJSON (fetched by us) otherwise. */
async function sourceFor(info) {
  if (info.delivery === "tiles") {
    // A plain string: new URL() would percent-encode the {z}/{x}/{y} placeholders.
    return { type: "vector", tiles: [`${location.origin}${info.url}`], minzoom: 7, maxzoom: 14 }; // as cut by pipeline/layer_tiles.py
  }
  const path = info.url.replace(/^\/api\/v1\//, "");
  return { type: "geojson", data: await getJson(path, {}, { cancelPrevious: false }) };
}

/** The filter of a style layer with the layer's switched-off parts left out. */
function withParts(spec, entry) {
  const parts = entry.info.parts || [];
  if (!parts.length || !entry.partsOff.size) return spec.filter;
  const kept = parts.filter((part) => !entry.partsOff.has(part.id)).map((part) => part.filter);
  return ["all", spec.filter, kept.length ? ["any", ...kept] : ["==", 1, 0]];
}

/** A registered layer's style layers, with its parts and visibility applied. */
const specsFor = (entry, colors) => styleLayersFor(entry.info, colors).map((spec) => (
  { ...spec, filter: withParts(spec, entry), layout: { ...spec.layout, visibility: entry.visible ? "visible" : "none" } }
));

/** Our sources and style layers, as they should be with the current colors. */
export function ownStyle() {
  const colors = readColors();
  const sources = {};
  const layers = [];
  for (const [id, entry] of registry) {
    sources[`src-${id}`] = entry.source;
    layers.push(...specsFor(entry, colors));
  }
  return { sources, layers };
}

let switchingStyle = false;

/** Call before map.setStyle(): until the new style loads, layers wait; then
 * anything registered meanwhile is added too. */
export function beginStyleSwitch(map) {
  switchingStyle = true;
  map.once("style.load", () => {
    switchingStyle = false;
    for (const id of registry.keys()) ensureOnMap(map, id);
  });
}

/** Add whatever of a registered layer the map doesn't have yet. */
function ensureOnMap(map, id) {
  if (switchingStyle) return; // the new style brings everything in the registry with it
  const entry = registry.get(id);
  if (!map.getSource(`src-${id}`)) map.addSource(`src-${id}`, entry.source);
  for (const spec of specsFor(entry, readColors())) {
    if (!map.getLayer(spec.id)) map.addLayer(spec);
  }
}

/** The ids of a layer's style layers that are on the map (see styles.js for the naming). */
const styleLayerIds = (map, id) => ["fill", "line", "point"].map((kind) => `lyr-${id}-${kind}`).filter((layerId) => map.getLayer(layerId));

/** Show a layer, downloading it the first time. */
export async function showLayer(map, info) {
  const known = registry.get(info.id);
  if (known) {
    known.visible = true;
    for (const layerId of styleLayerIds(map, info.id)) map.setLayoutProperty(layerId, "visibility", "visible");
    ensureOnMap(map, info.id);
    return;
  }
  if (!loading.has(info.id)) loading.set(info.id, sourceFor(info));
  let source;
  try {
    source = await loading.get(info.id);
  } finally {
    loading.delete(info.id);
  }
  const entry = registry.get(info.id) || { info, source, visible: true, partsOff: new Set() };
  registry.set(info.id, entry);
  ensureOnMap(map, info.id);
  for (const layerId of styleLayerIds(map, info.id)) {
    map.setLayoutProperty(layerId, "visibility", entry.visible ? "visible" : "none");
  }
}

/** Hide a layer (it stays loaded for next time). */
export function hideLayer(map, id) {
  const entry = registry.get(id);
  if (entry) entry.visible = false;
  for (const layerId of styleLayerIds(map, id)) map.setLayoutProperty(layerId, "visibility", "none");
}

/** Turn one part of a layer (e.g. photo locations) on or off. */
export function setPartVisible(map, id, partId, on) {
  const entry = registry.get(id);
  if (!entry) return;
  if (on) entry.partsOff.delete(partId);
  else entry.partsOff.add(partId);
  for (const spec of styleLayersFor(entry.info, readColors())) {
    if (map.getLayer(spec.id)) map.setFilter(spec.id, withParts(spec, entry));
  }
}

/** The GeoJSON of a loaded layer (for the county outlines), or undefined. */
export const loadedData = (id) => registry.get(id)?.source?.data;
