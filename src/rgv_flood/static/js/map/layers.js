/* Puts layers on the map, shows and hides them, and keeps them across theme
 * switches.
 *
 * Every layer the reader turns on is downloaded once and kept in `registry`
 * (its source spec, with GeoJSON data held in memory, and its info). The map
 * itself can be rebuilt from the registry at any time, which is what a theme
 * switch does: the basemap changes, our sources and style layers are re-added
 * from memory with the new theme's colors, and nothing is downloaded again. */

import { getJson } from "../api.js";
import {
  FLOOD_PHOTO_CLUSTER_RADIUS, FLOOD_PHOTO_LAYER, FLOOD_PHOTO_LOCATION_SOURCE, FLOOD_PHOTO_OPENABLE_SOURCE,
} from "./flood-photo-layer.js";
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
  const source = { type: "geojson", data: await getJson(path, {}, { cancelPrevious: false }) };
  // Native GeoJSON clustering is computed in MapLibre's worker, which keeps all
  // source features available while avoiding thousands of overlapping circles.
  // The deliberately modest radius limits aggregation to nearby markers instead
  // of turning the county into one catch-all bubble.
  if (info.id === FLOOD_PHOTO_LAYER) Object.assign(source, { cluster: true, clusterRadius: FLOOD_PHOTO_CLUSTER_RADIUS, clusterMaxZoom: 14 });
  return source;
}

/** The photo source after its two panel parts have been applied.
 *
 * Clustering happens before a style filter, so filtering only the style would
 * leave a cluster count that includes hidden photos. Replacing the source data
 * makes the displayed cluster represent exactly the parts the reader enabled.
 */
function visibleSource(entry) {
  if (entry.info.id !== FLOOD_PHOTO_LAYER || !entry.partsOff.size) return entry.source;
  const showPhotos = !entry.partsOff.has("photos");
  const showLocations = !entry.partsOff.has("locations");
  const features = entry.source.data.features.filter((feature) => (
    feature.properties.photo_url ? showPhotos : showLocations
  ));
  return { ...entry.source, data: { ...entry.source.data, features } };
}

/** Keep published photos and photo-location records in separate cluster trees. */
function photoSources(entry) {
  const data = visibleSource(entry).data;
  const source = (features) => ({ type: "geojson", data: { ...data, features }, cluster: true, clusterRadius: FLOOD_PHOTO_CLUSTER_RADIUS, clusterMaxZoom: 14 });
  return {
    [FLOOD_PHOTO_OPENABLE_SOURCE]: source(data.features.filter((feature) => feature.properties.photo_url)),
    [FLOOD_PHOTO_LOCATION_SOURCE]: source(data.features.filter((feature) => !feature.properties.photo_url)),
  };
}

/** The filter of a style layer with the layer's switched-off parts left out. */
function withParts(spec, entry) {
  // Flood-photo parts are applied to their separate source trees. Applying the
  // source-record predicates again to an aggregate cluster would hide it:
  // clusters have point_count, not the member record's photo_url.
  if (entry.info.id === FLOOD_PHOTO_LAYER) return spec.filter;
  const parts = entry.info.parts || [];
  if (!parts.length || !entry.partsOff.size) return spec.filter;
  const kept = parts.filter((part) => !entry.partsOff.has(part.id)).map((part) => part.filter);
  return ["all", spec.filter, kept.length ? ["any", ...kept] : ["==", 1, 0]];
}

// Layers sharing a panel row stack with the more severe on top: the TWDB 0.2%
// extent holds the whole 1% extent, which would otherwise be hidden under it.
const SEVERITY_RANK = { "sev-mod": 1, "sev-high": 2 };
const rank = (entry) => SEVERITY_RANK[entry.info.legend.color] || 0;

/** Registered layers in drawing order: rows as they were first shown, each row's layers by rank. */
function stackOrder() {
  const entries = [...registry.values()];
  const rows = [...new Set(entries.map((entry) => entry.info.panel_row))];
  return entries.sort((a, b) => rows.indexOf(a.info.panel_row) - rows.indexOf(b.info.panel_row) || rank(a) - rank(b));
}

/** The style layer a new layer of `entry` goes beneath: the lowest of its more severe row-mates (or none). */
function beneath(map, entry) {
  const above = new Set(stackOrder()
    .filter((other) => other.info.panel_row === entry.info.panel_row && rank(other) > rank(entry))
    .flatMap((other) => styleLayerIds(map, other.info.id)));
  return map.getLayersOrder().find((id) => above.has(id));
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
  for (const entry of stackOrder()) {
    if (entry.info.id === FLOOD_PHOTO_LAYER) Object.assign(sources, photoSources(entry));
    else sources[`src-${entry.info.id}`] = visibleSource(entry);
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
  if (entry.info.id === FLOOD_PHOTO_LAYER) {
    for (const [sourceId, source] of Object.entries(photoSources(entry))) {
      if (!map.getSource(sourceId)) map.addSource(sourceId, source);
    }
  } else if (!map.getSource(`src-${id}`)) map.addSource(`src-${id}`, visibleSource(entry));
  const before = beneath(map, entry);
  for (const spec of specsFor(entry, readColors())) {
    if (!map.getLayer(spec.id)) map.addLayer(spec, before);
  }
}

/** The ids of a layer's style layers that are on the map (see styles.js for the naming). */
const styleLayerIds = (map, id) => (registry.get(id) ? styleLayersFor(registry.get(id).info, readColors()) : [])
  .map((spec) => spec.id).filter((layerId) => map.getLayer(layerId));

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
  if (entry.info.id === FLOOD_PHOTO_LAYER) {
    for (const [sourceId, source] of Object.entries(photoSources(entry))) map.getSource(sourceId).setData(source.data);
  }
  for (const spec of styleLayersFor(entry.info, readColors())) {
    if (map.getLayer(spec.id)) map.setFilter(spec.id, withParts(spec, entry));
  }
}

/** The GeoJSON of a loaded layer (for the county outlines), or undefined. */
export const loadedData = (id) => registry.get(id)?.source?.data;
