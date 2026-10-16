/* Map popups and the selection ring.
 *
 * A click on the map picks the top feature of our layers and describes it as
 * a small model (title, lines, body, note, image or gallery). The model is
 * rendered into the <template id="popup-template"> with textContent only, so
 * every value from the data is escaped. The clicked feature gets the brand
 * orange ring, the one place the map shows the UTRGV color. */

import { mapReady, maplibregl } from "./main.js";

const HCDD1 = "Hidalgo County Drainage District No. 1";
const TWDB = "Texas Water Development Board, 2024 State Flood Plan";
const PHOTO_PIXELS = 520; // twice the popup's photo width, for sharp screens

const WATERWAY_KINDS = { drain: "Drain or floodway", resaca: "Resaca", canal: "Irrigation canal", canal_or_ditch: "Canal or ditch", creek: "Creek or arroyo" };
const FLOOD_WORK_KINDS = { dam: "Dam", levee: "Levee", sea_wall: "Sea wall", storm_drain: "Storm drain system", coastal: "Coastal works", low_water_crossing: "Low-water crossing", other: "Flood infrastructure" };
const CITY_DRAINAGE_KINDS = { ditch: "Drainage ditch", storm_sewer: "Storm sewer", detention_pond: "Detention pond" };
const DRAINAGE_KINDS = { channel: "Drainage channel", planned_channel: "Planned channel", detention_pond: "Detention pond", gate: "Gate", pump: "Pump" };
const REPORT_KINDS = { flash_flood: "Flash flood", flood: "Flood", heavy_rain: "Heavy rain", coastal_flood: "Coastal flood" };

const dollars = (n) => `$${Math.round(n).toLocaleString()}`;
const joined = (...parts) => parts.filter(Boolean).join(" · ");
const valleyTime = (iso) => new Date(iso).toLocaleString("en-US", { timeZone: "America/Chicago", dateStyle: "medium", timeStyle: "short" });
// MapLibre hands nested properties back as JSON text.
const parsed = (value) => (typeof value === "string" ? JSON.parse(value) : value);
const sized = (url) => (url.startsWith("http") ? `${url}${url.includes("?") ? "&" : "?"}w=${PHOTO_PIXELS}` : url);

/** What to show for a feature, by the kind of feature it is. */
function describe(p, layerId) {
  switch (p.overlay_type) {
    case "fema_photos": {
      const photos = parsed(p.photos) || [];
      return {
        title: joined(p.town, `${p.county} County`),
        lines: [`${photos.length} FEMA photo${photos.length === 1 ? "" : "s"} of flooding`],
        gallery: photos,
        note: "Placed at the town FEMA's caption names, not where each photo was taken. Public domain, via Wikimedia Commons.",
      };
    }
    case "flood_photo":
      return p.photo_url
        ? { title: "Flood photo", lines: [p.event, p.taken && `Taken ${p.taken}`], image: { src: sized(p.photo_url), href: p.photo_url, alt: `District photo, ${p.event}` },
            note: `${HCDD1}. Shows where crews documented conditions, not necessarily standing water.` }
        : { title: "Photo location", lines: [p.event, p.taken && `Photo taken ${p.taken}`],
            note: `A crew from ${HCDD1} photographed conditions here. The district has not published the image.` };
    case "waterway": {
      const kind = WATERWAY_KINDS[p.kind] || "Waterway";
      return { title: p.name || kind, lines: [joined(kind, `${p.county} County`)], note: "U.S. Census Bureau water lines. The kind is read from the line's own name." };
    }
    case "flood_infrastructure": {
      const kind = FLOOD_WORK_KINDS[p.kind] || "Flood infrastructure";
      return {
        title: p.name || kind,
        lines: [joined(kind, p.county && `${p.county} County`), p.description !== p.name && p.description, p.condition && `Condition: ${p.condition}`],
        note: p.source ? `Source: ${p.source} (OpenStreetMap)` : TWDB,
      };
    }
    case "flood_project": {
      const ongoing = p.stage === "ongoing";
      const facts = ongoing
        ? [p.cost && `Cost ${dollars(p.cost)}`, p.funding && `funded by ${p.funding}`, p.year && `due ${p.year}`]
        : [p.project_type, p.cost && `estimated ${dollars(p.cost)}`];
      const buildings = !ongoing && p.structures_at_risk != null
        ? `Buildings in the 100-year floodplain: ${p.structures_at_risk.toLocaleString()} now, ${(p.structures_still_at_risk ?? 0).toLocaleString()} after`
        : null;
      return { title: p.name || "Flood project", lines: [joined(ongoing ? "Ongoing project" : "Recommended in the state flood plan", `${p.county} County`), joined(...facts), buildings], body: p.description, note: TWDB };
    }
    case "city_drainage": {
      const kind = CITY_DRAINAGE_KINDS[p.kind] || "Drainage";
      return { title: p.name || kind, lines: [joined(kind, p.city), p.owner && `Owner: ${p.owner}`, (p.size || p.material) && `Pipe: ${joined(p.size, p.material)}`], note: `City of ${p.city}` };
    }
    case "storm_report":
      return {
        title: `${REPORT_KINDS[p.kind] || "Flood"} report`,
        lines: [joined(valleyTime(p.reported_at), p.city, `${p.county} County`), p.magnitude && `Rain reported: ${p.magnitude} in`],
        body: p.remark,
        note: `Reported to NWS Brownsville${p.source ? ` by: ${p.source}` : ""}`,
      };
    case "flood_extent":
      return { title: `Mapped flooding, ${p.year}`, lines: [`District label for this event: ${p.hcdd1_label}`],
               note: `${p.source}. The label is the district's own; whether it is rainfall or flood depth isn't stated.` };
    case "drainage":
      return { title: p.name, lines: [joined(DRAINAGE_KINDS[p.kind] || "Drainage", p.acres ? `${p.acres} acres` : p.owner)], note: HCDD1 };
    case "bond_project": {
      const years = p.start_year && p.end_year ? `${p.start_year}–${p.end_year}` : p.start_year && `started ${p.start_year}`;
      return { title: p.name, lines: [joined(p.program, p.status, years)], body: p.description, note: HCDD1 };
    }
    case "claims": {
      const moved = p.from_old_tracts ? ` About ${Number(p.from_old_tracts).toLocaleString()} were filed under older tract boundaries and are spread across the tracts that replaced them.` : "";
      return {
        title: `${Number(p.claims).toLocaleString()} flood insurance claim${p.claims === 1 ? "" : "s"}`,
        lines: [joined(`Tract ${p.geoid}`, `${p.county} County`), joined(`Paid: ${dollars(p.paid)}`, `years: ${p.first_year && p.last_year ? `${p.first_year}–${p.last_year}` : "none on record"}`), p.top_event && `Most common event: ${p.top_event}`],
        note: `FEMA NFIP claims. Raw counts, not adjusted for how many homes are insured.${moved}`,
      };
    }
    default:
      break;
  }
  if (layerId === "noaa-flood-events") {
    return { title: joined(p.type, p.location), lines: [p.date], body: p.summary, note: "NOAA Storm Events Database", link: p.source_url };
  }
  if (layerId === "live-alerts") {
    return { title: p.summary, lines: [joined(p.source_publisher, p.expires_at && `until ${valleyTime(p.expires_at)}`)], note: "Official live signal", link: p.source_url };
  }
  if (p.infrastructure_type) return { title: p.name || "Bridge", lines: [joined("Bridge", p.county && `${p.county} County`)], note: "Source: Overture Maps Foundation (OpenStreetMap)" };
  return { title: p.source || "Flood zone", lines: [`Zone ${p.original_category || "—"}`, `Relative severity: ${p.relative_class || "uncategorized"}`] };
}

const field = (root, name) => root.querySelector(`[data-field="${name}"]`);

function setText(element, text) {
  element.textContent = text || "";
  element.hidden = !text;
}

/** One photo of the gallery: counter, big image, caption, credit, current thumbnail. */
function showPhoto(root, photos, index) {
  const photo = photos[index];
  root.dataset.index = String(index);
  root.querySelector("[data-counter]").textContent = `${index + 1} / ${photos.length}`;
  const image = root.querySelector("[data-gallery-image]");
  image.src = photo.thumb_url;
  image.alt = photo.caption;
  root.querySelector("[data-gallery-link]").href = photo.page_url;
  root.querySelector("[data-caption]").textContent = photo.caption;
  root.querySelector("[data-credit]").textContent = joined(photo.taken, `Photo: ${photo.credit}/FEMA`);
  root.querySelectorAll("[data-thumb]").forEach((thumb, i) => thumb.setAttribute("aria-current", String(i === index)));
}

function renderGallery(root, photos) {
  const thumbs = root.querySelector("[data-thumbs]");
  photos.forEach((photo, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "gal-thumb";
    button.dataset.thumb = String(i);
    button.setAttribute("aria-label", `Photo ${i + 1}`);
    const thumb = document.createElement("img");
    thumb.src = photo.thumb_url;
    thumb.alt = "";
    thumb.className = "h-full w-full object-cover";
    button.append(thumb);
    button.addEventListener("click", () => showPhoto(root, photos, i));
    thumbs.append(button);
  });
  root.querySelectorAll("[data-step]").forEach((button) => {
    button.hidden = photos.length < 2;
    button.addEventListener("click", () => {
      const next = (Number(root.dataset.index) + Number(button.dataset.step) + photos.length) % photos.length;
      showPhoto(root, photos, next);
    });
  });
  showPhoto(root, photos, 0);
}

/** The popup's DOM for a model. */
export function renderPopup(model) {
  const root = document.getElementById("popup-template").content.firstElementChild.cloneNode(true);
  setText(field(root, "title"), model.title);
  const lines = field(root, "lines");
  for (const line of (model.lines || []).filter(Boolean)) {
    const div = document.createElement("div");
    div.textContent = line;
    lines.append(div);
  }
  setText(field(root, "body"), model.body);
  setText(field(root, "note"), model.note);
  const link = field(root, "link");
  link.hidden = !model.link;
  if (model.link) link.href = model.link;

  const image = root.querySelector("[data-image]");
  if (model.image) {
    image.href = model.image.href;
    const img = image.querySelector("img");
    img.src = model.image.src;
    img.alt = model.image.alt;
  } else {
    image.remove();
  }
  const gallery = root.querySelector("[data-gallery]");
  if (model.gallery?.length) renderGallery(gallery, model.gallery);
  else gallery.remove();
  return root;
}

// ---- the selection ring ----

let selected = null; // [lng, lat]

function drawSelection(map) {
  const data = { type: "FeatureCollection", features: selected ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: selected } }] : [] };
  if (map.getSource("selection")) {
    map.getSource("selection").setData(data);
    return;
  }
  map.addSource("selection", { type: "geojson", data });
  const brand = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim();
  map.addLayer({
    id: "lyr-selection", type: "circle", source: "selection",
    paint: { "circle-radius": 15, "circle-color": brand, "circle-opacity": 0.14, "circle-stroke-color": brand, "circle-stroke-width": 2 },
  });
}

/** Ring a place on the map (null clears it). */
export async function select(lngLat) {
  selected = lngLat;
  drawSelection(await mapReady);
}

const interactiveLayers = (map) =>
  (map.getStyle()?.layers || [])
    .filter((layer) => layer.id.startsWith("lyr-") && layer.id !== "lyr-selection" && !layer.id.startsWith("lyr-county-boundaries"))
    .filter((layer) => map.getLayoutProperty(layer.id, "visibility") !== "none")
    .map((layer) => layer.id);

const layerIdOf = (styleLayerId) => styleLayerId.replace(/^lyr-/, "").replace(/-(fill|line|point)$/, "");

mapReady.then((map) => {
  const popup = new maplibregl.Popup({ maxWidth: "320px", focusAfterOpen: false });
  popup.on("close", () => select(null));

  map.on("click", (event) => {
    const layers = interactiveLayers(map);
    if (!layers.length) return;
    const [feature] = map.queryRenderedFeatures(event.point, { layers });
    if (!feature) return;
    const at = feature.geometry.type === "Point" ? feature.geometry.coordinates : event.lngLat.toArray();
    popup.setLngLat(at).setDOMContent(renderPopup(describe(feature.properties, layerIdOf(feature.layer.id)))).addTo(map);
    select(at);
  });
  map.on("mousemove", (event) => {
    const layers = interactiveLayers(map);
    const hit = layers.length && map.queryRenderedFeatures(event.point, { layers }).length;
    map.getCanvas().style.cursor = hit ? "pointer" : "";
  });
  map.on("style.load", () => drawSelection(map)); // keep the ring across theme switches
});
