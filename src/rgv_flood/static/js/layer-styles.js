/* Colors and legends for every map layer.
 *
 * Severity (hazard) and infrastructure colors are defined once, in app.css
 * (--sev-* and --infra-*), and read from there, so the sidebar swatches and the
 * map can't drift apart. Infrastructure and evidence overlays are not hazard
 * ratings, so they use hues that stay apart from the severity palette.
 */

const stylesheet = getComputedStyle(document.documentElement);
const cssVar = (name) => stylesheet.getPropertyValue(name).trim();

function severity(level) {
  return {
    color: cssVar(`--sev-${level}-line`),
    weight: 1,
    fillColor: cssVar(`--sev-${level}`),
    fillOpacity: parseFloat(cssVar(`--sev-${level}-opacity`)),
  };
}
const SEVERITY = Object.fromEntries(["high", "moderate", "low", "uncategorized"].map((level) => [level, severity(level)]));
const BOUNDARY = { color: "#1b2a4a", weight: 1.5, fill: false, dashArray: "3 3" };

const BRIDGE = cssVar("--infra-bridge");
export const INFRA = {
  bridge: { color: BRIDGE, weight: 2, fillColor: BRIDGE, fillOpacity: 0.35 },
};

export const OVERLAY = {
  extent: { color: "#14518c", weight: 1, fillColor: "#1e6bb8", fillOpacity: 0.5 },
  // Two different things, so two colors and two names: a photo you can open
  // (magenta, a hue no other point on the map uses), and a place where the
  // district took a photo it hasn't published (grey).
  photo: { radius: 3.5, color: "#ffffff", weight: 0.8, fillColor: "#c026d3", fillOpacity: 0.95 },
  photo_location: { radius: 3, color: "#ffffff", weight: 0.6, fillColor: "#94a3b8", fillOpacity: 0.8 },
  // A town with FEMA photos: the same magenta as a photo you can open, larger
  // and ringed, since one dot holds several photos.
  town_photos: { radius: 8, color: "#701a75", weight: 2, fillColor: "#c026d3", fillOpacity: 0.9 },
  channel: { color: "#475569", weight: 1.5 },
  planned_channel: { color: "#475569", weight: 1.5, dashArray: "5 4" },
  detention_pond: { color: "#0369a1", weight: 1, fillColor: "#38bdf8", fillOpacity: 0.45 },
  gate: { radius: 4, color: "#0e7490", weight: 1.5, fillColor: "#ffffff", fillOpacity: 1 },
  pump: { radius: 4, color: "#ffffff", weight: 1, fillColor: "#be123c", fillOpacity: 1 },
};

// Drains, canals and creeks: blues, darkest for the lines built to carry
// runoff away, dashed and lightest for natural creeks.
export const WATERWAY = {
  drain: { color: "#0f4c81", weight: 2.2 },
  resaca: { color: "#2563eb", weight: 1.6 },
  canal: { color: "#0891b2", weight: 1.4 },
  canal_or_ditch: { color: "#64748b", weight: 1 },
  creek: { color: "#60a5fa", weight: 1.2, dashArray: "4 3" },
};

// Flood works in the state flood plan.
export const FLOOD_WORKS = {
  dam: { radius: 5, color: "#ffffff", weight: 1, fillColor: "#92400e", fillOpacity: 1 },
  low_water_crossing: { radius: 5, color: "#ffffff", weight: 1, fillColor: "#dc2626", fillOpacity: 1 },
  levee: { color: "#78350f", weight: 3 },
  sea_wall: { color: "#57534e", weight: 3 },
  storm_drain: { color: "#334155", weight: 1.4 },
  coastal: { radius: 4, color: "#ffffff", weight: 1, fillColor: "#0e7490", fillOpacity: 1 },
  other: { radius: 4, color: "#78716c", weight: 1.5, fillColor: "#a8a29e", fillOpacity: 0.35 },
};

export const PROJECT_STAGE_COLORS = { ongoing: "#ea580c", recommended: "#4f46e5" };

export const CITY_DRAINAGE = {
  storm_sewer: { color: "#475569", weight: 0.8 },
  ditch: { color: "#1e3a8a", weight: 1.8 },
  detention_pond: OVERLAY.detention_pond,
};

// Flood reports to the NWS, by what was reported.
export const REPORT_COLORS = { flash_flood: "#1d4ed8", flood: "#0ea5e9", heavy_rain: "#64748b", coastal_flood: "#0f766e" };

const BOND_STATUS_COLORS = {
  "Pre-design": "#94a3b8",
  Design: "#8b5cf6",
  Construction: "#f97316",
  Complete: "#16a34a",
};
const CLAIMS_RAMP = ["#ffffff", "#fce7f3", "#f9a8d4", "#ec4899", "#be185d", "#831843"];

/** Style for any feature. Leaflet applies this to every feature of a layer,
 * points included, after they are created, so each kind needs a case here or
 * it falls through to the grey "uncategorized" severity style. */
export function styleFor(feature) {
  const p = feature.properties || {};
  if (p.original_category === "county boundary") return BOUNDARY;
  if (p.infrastructure_type) return INFRA.bridge;

  switch (p.overlay_type) {
    case "flood_extent":
      return OVERLAY.extent;
    case "fema_photos":
      return OVERLAY.town_photos;
    case "flood_photo":
      return p.photo_url ? OVERLAY.photo : OVERLAY.photo_location;
    case "drainage":
      return OVERLAY[p.kind] || OVERLAY.channel;
    case "bond_project": {
      const color = BOND_STATUS_COLORS[p.status] || BOND_STATUS_COLORS["Pre-design"];
      return { color, weight: 1.2, fillColor: color, fillOpacity: 0.35 };
    }
    case "waterway":
      return WATERWAY[p.kind] || WATERWAY.canal_or_ditch;
    case "flood_infrastructure":
      return FLOOD_WORKS[p.kind] || FLOOD_WORKS.other;
    case "flood_project": {
      const color = PROJECT_STAGE_COLORS[p.stage] || PROJECT_STAGE_COLORS.recommended;
      return { color, weight: 1.2, fillColor: color, fillOpacity: 0.3 };
    }
    case "city_drainage":
      return CITY_DRAINAGE[p.kind] || CITY_DRAINAGE.ditch;
    case "storm_report":
      return { radius: 4.5, color: "#ffffff", weight: 1, fillColor: REPORT_COLORS[p.kind] || REPORT_COLORS.flood, fillOpacity: 0.95 };
    case "claims": {
      const level = p.claims_class || 0;
      return { color: "#b08aa0", weight: 0.6, fillColor: CLAIMS_RAMP[level], fillOpacity: level ? 0.5 : 0 };
    }
  }
  return SEVERITY[p.relative_class] || SEVERITY.uncategorized;
}

/** Marker style for a point feature: its style, sized as a dot. */
export function pointStyleFor(feature) {
  return { radius: 5, ...styleFor(feature) };
}

// Legend rows for the layers that aren't covered by the static severity /
// infrastructure legends in the sidebar. Colors come from the styles above.
export const LEGENDS = {
  "hcdd1-flood-extents": [{ shape: "square", color: OVERLAY.extent.fillColor, label: "Mapped flooding" }],
  "hcdd1-flood-photos": [
    { shape: "dot", color: OVERLAY.photo.fillColor, label: "Flood photo (click to view)", part: "photos" },
    { shape: "dot", color: OVERLAY.photo_location.fillColor, label: "Photo location (image not published)", part: "locations" },
  ],
  "fema-flood-photos": [
    { shape: "dot", color: OVERLAY.town_photos.fillColor, label: "Town FEMA photographed flooding (click to view)" },
  ],
  "hcdd1-drainage": [
    { shape: "line", color: OVERLAY.channel.color, label: "Channel" },
    { shape: "dash", color: OVERLAY.planned_channel.color, label: "Planned channel" },
    { shape: "square", color: OVERLAY.detention_pond.fillColor, label: "Detention pond" },
    { shape: "ring", color: OVERLAY.gate.color, label: "Gate" },
    { shape: "dot", color: OVERLAY.pump.fillColor, label: "Pump" },
  ],
  "hcdd1-bond-projects": Object.entries(BOND_STATUS_COLORS).map(([status, color]) => ({
    shape: "square",
    color,
    label: `Project: ${status.toLowerCase()}`,
  })),
  waterways: [
    { shape: "line", color: WATERWAY.drain.color, label: "Drain or floodway" },
    { shape: "line", color: WATERWAY.resaca.color, label: "Resaca" },
    { shape: "line", color: WATERWAY.canal.color, label: "Irrigation canal" },
    { shape: "line", color: WATERWAY.canal_or_ditch.color, label: "Canal or ditch (unnamed)" },
    { shape: "dash", color: WATERWAY.creek.color, label: "Creek or arroyo" },
  ],
  "flood-infrastructure": [
    { shape: "dot", color: FLOOD_WORKS.dam.fillColor, label: "Dam" },
    { shape: "dot", color: FLOOD_WORKS.low_water_crossing.fillColor, label: "Low-water crossing" },
    { shape: "line", color: FLOOD_WORKS.levee.color, label: "Levee" },
    { shape: "line", color: FLOOD_WORKS.sea_wall.color, label: "Sea wall" },
    { shape: "line", color: FLOOD_WORKS.storm_drain.color, label: "Storm drain system" },
    { shape: "dot", color: FLOOD_WORKS.coastal.fillColor, label: "Coastal works (dune, jetty, beach)" },
  ],
  "city-drainage": [
    { shape: "line", color: CITY_DRAINAGE.ditch.color, label: "Drainage ditch" },
    { shape: "line", color: CITY_DRAINAGE.storm_sewer.color, label: "Storm sewer" },
    { shape: "square", color: CITY_DRAINAGE.detention_pond.fillColor, label: "Detention pond" },
  ],
  "flood-projects": [
    { shape: "square", color: PROJECT_STAGE_COLORS.ongoing, label: "Ongoing project" },
    { shape: "square", color: PROJECT_STAGE_COLORS.recommended, label: "Recommended in the state plan" },
  ],
  "nws-flood-reports": [
    { shape: "dot", color: REPORT_COLORS.flash_flood, label: "Flash flood report" },
    { shape: "dot", color: REPORT_COLORS.flood, label: "Flood report" },
    { shape: "dot", color: REPORT_COLORS.heavy_rain, label: "Heavy rain report" },
    { shape: "dot", color: REPORT_COLORS.coastal_flood, label: "Coastal flood report" },
  ],
  "nfip-claims-by-tract": [
    { ramp: CLAIMS_RAMP.slice(1), label: "Insurance claims per tract (fewer → more)" },
  ],
};

// Layers whose features fall into parts a reader can switch on and off one at a
// time, under the layer's own checkbox. Listed in sidebar order; the first is
// drawn on top. A legend row with the same `part` hides along with it.
export const LAYER_PARTS = {
  "hcdd1-flood-photos": [
    { id: "photos", label: "Photos you can open", includes: (p) => Boolean(p.photo_url) },
    { id: "locations", label: "Photo locations only", includes: (p) => !p.photo_url },
  ],
};
