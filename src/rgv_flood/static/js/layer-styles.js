/* Colors and legends for every map layer.
 *
 * Severity (hazard) fills are lighter tints of the sidebar swatches (app.css
 * --sev-*), since they are drawn semi-transparent over the basemap.
 * Infrastructure and evidence overlays are not hazard ratings, so they use
 * separate hues that stay apart from that palette (app.css --infra-*).
 */

const SEVERITY = {
  high: { color: "#a83232", weight: 1, fillColor: "#d64545", fillOpacity: 0.38 },
  moderate: { color: "#b06d22", weight: 1, fillColor: "#e0913a", fillOpacity: 0.34 },
  low: { color: "#3f68a8", weight: 1, fillColor: "#5b8bd6", fillOpacity: 0.28 },
  uncategorized: { color: "#7c8296", weight: 1, fillColor: "#aeb3c2", fillOpacity: 0.25 },
};
const BOUNDARY = { color: "#1b2a4a", weight: 1.5, fill: false, dashArray: "3 3" };

export const INFRA = {
  bridge: { color: "#7c3aed", weight: 2, fillColor: "#7c3aed", fillOpacity: 0.35 },
  dam: { color: "#0d9488", weight: 1, fillColor: "#0d9488", fillOpacity: 0.45 },
};

export const OVERLAY = {
  extent: { color: "#14518c", weight: 1, fillColor: "#1e6bb8", fillOpacity: 0.5 },
  photo: { radius: 3, color: "#ffffff", weight: 0.6, fillColor: "#0f172a", fillOpacity: 0.85 },
  channel: { color: "#475569", weight: 1.5 },
  planned_channel: { color: "#475569", weight: 1.5, dashArray: "5 4" },
  detention_pond: { color: "#0369a1", weight: 1, fillColor: "#38bdf8", fillOpacity: 0.45 },
  gate: { radius: 4, color: "#0e7490", weight: 1.5, fillColor: "#ffffff", fillOpacity: 1 },
  pump: { radius: 4, color: "#ffffff", weight: 1, fillColor: "#be123c", fillOpacity: 1 },
};

const BOND_STATUS_COLORS = {
  "Pre-design": "#94a3b8",
  Design: "#8b5cf6",
  Construction: "#f97316",
  Complete: "#16a34a",
};
const CLAIMS_RAMP = ["#ffffff", "#fce7f3", "#f9a8d4", "#ec4899", "#be185d", "#831843"];

/** Path style for a polygon or line feature. */
export function styleFor(feature) {
  const p = feature.properties || {};
  if (p.original_category === "county boundary") return BOUNDARY;
  if (p.infrastructure_type) return INFRA[p.infrastructure_type] || INFRA.bridge;

  switch (p.overlay_type) {
    case "flood_extent":
      return OVERLAY.extent;
    case "drainage":
      return OVERLAY[p.kind] || OVERLAY.channel;
    case "bond_project": {
      const color = BOND_STATUS_COLORS[p.status] || BOND_STATUS_COLORS["Pre-design"];
      return { color, weight: 1.2, fillColor: color, fillOpacity: 0.35 };
    }
    case "claims": {
      const level = p.claims_class || 0;
      return { color: "#b08aa0", weight: 0.6, fillColor: CLAIMS_RAMP[level], fillOpacity: level ? 0.5 : 0 };
    }
  }
  return SEVERITY[p.relative_class] || SEVERITY.uncategorized;
}

/** Marker style for a point feature (photos, gates, pumps, point-shaped dams). */
export function pointStyleFor(feature) {
  const p = feature.properties || {};
  if (p.overlay_type === "flood_photo") return OVERLAY.photo;
  if (p.overlay_type === "drainage") return OVERLAY[p.kind] || OVERLAY.gate;
  return { radius: 5, ...(INFRA[p.infrastructure_type] || INFRA.bridge) };
}

// Legend rows for the layers that aren't covered by the static severity /
// infrastructure legends in the sidebar. Colors come from the styles above.
export const LEGENDS = {
  "hcdd1-flood-extents": [{ shape: "square", color: OVERLAY.extent.fillColor, label: "Mapped flooding" }],
  "hcdd1-flood-photos": [{ shape: "dot", color: OVERLAY.photo.fillColor, label: "Flood response photo" }],
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
  "nfip-claims-by-tract": [
    { ramp: CLAIMS_RAMP.slice(1), label: "Insurance claims per tract (fewer → more)" },
  ],
};
