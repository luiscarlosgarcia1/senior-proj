/* The page address keeps the view, so a link shares exactly what you see:
 *
 *   #county=hidalgo&layers=fema-nfhl,hcdd1-flood-photos&off=hcdd1-flood-photos.locations&event=<id>&map=26.2,-98.2,11
 *
 * Reading is forgiving: unknown layers and parts, a county that isn't one of
 * the four and a malformed map view are ignored, and `events=1` turns on the
 * NOAA flood events layer. */

import { mapReady } from "./map/main.js";

const COUNTIES = new Set(["cameron", "hidalgo", "starr", "willacy"]);
const list = (value) => (value || "").split(",").map((item) => item.trim()).filter(Boolean);

/** The state a hash asks for, with anything malformed dropped. */
export function readHash(hash = location.hash) {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const layers = new Set(list(params.get("layers")));
  if (params.get("events") === "1") layers.add("noaa-flood-events");
  const view = list(params.get("map")).map(Number);
  const validView = view.length === 3 && view.every(Number.isFinite) && Math.abs(view[0]) <= 90 && Math.abs(view[1]) <= 180;
  const county = params.get("county");
  return {
    county: COUNTIES.has(county) ? county : "",
    layers,
    off: new Set(list(params.get("off")).filter((key) => /^[\w-]+\.[\w-]+$/.test(key))),
    event: params.get("event") || null,
    map: validView ? { lat: view[0], lng: view[1], zoom: view[2] } : null,
  };
}

/** The hash for a state (empty parts left out). */
export function writeHash(state) {
  const parts = {
    county: state.county,
    layers: [...state.layers].join(","),
    off: [...state.off].join(","),
    event: state.event,
    map: state.map ? `${state.map.lat.toFixed(4)},${state.map.lng.toFixed(4)},${state.map.zoom.toFixed(2)}` : "",
  };
  return Object.entries(parts).filter(([, value]) => value).map(([key, value]) => `${key}=${value}`).join("&");
}

const until = (check) => new Promise((resolve) => {
  const tick = () => (check() ? resolve() : setTimeout(tick, 30));
  tick();
});

async function apply(Alpine, map, state) {
  const layers = Alpine.store("layers");
  const known = (id) => layers.info(id);
  for (const key of state.off) {
    const [layerId, partId] = key.split(".");
    if ((known(layerId)?.parts || []).some((part) => part.id === partId)) layers.partsOff[key] = true;
  }
  if (state.county) Alpine.store("app").setCounty(state.county);
  for (const id of state.layers) {
    const info = known(id);
    if (info && !layers.on[id]) layers.setLayer(info, true);
  }
  if (state.event) await Alpine.store("events").openById(state.event, { fly: !state.map });
  if (state.map) {
    await new Promise((resolve) => setTimeout(resolve, 650)); // after any county fit has run
    map.jumpTo({ center: [state.map.lng, state.map.lat], zoom: state.map.zoom });
  }
}

function current(Alpine, map) {
  const layers = Alpine.store("layers");
  const center = map.getCenter();
  return {
    county: Alpine.store("app").county,
    layers: Object.keys(layers.on).filter((id) => layers.on[id]),
    off: Object.keys(layers.partsOff).filter((key) => layers.partsOff[key]),
    event: Alpine.store("events").selectedId,
    map: { lat: center.lat, lng: center.lng, zoom: map.getZoom() },
  };
}

document.addEventListener("alpine:init", async () => {
  const Alpine = window.Alpine;
  const map = await mapReady;
  await until(() => Alpine.store("layers").loaded);
  await apply(Alpine, map, readHash());

  const save = () => history.replaceState(null, "", `#${writeHash(current(Alpine, map))}`);
  Alpine.effect(save); // reruns whenever county, layers, parts or event change
  map.on("moveend", save);
  window.addEventListener("hashchange", () => apply(Alpine, map, readHash()));
});
