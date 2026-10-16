/* How each layer looks on the map, as MapLibre style layers.
 *
 * Every layer gets up to three style layers, one per kind of geometry:
 * `lyr-<id>-fill` (polygons), `lyr-<id>-line` (lines and polygon outlines) and
 * `lyr-<id>-point`. Colors come from the design tokens (the CSS variables in
 * input.css), so a theme switch only needs `readColors()` again. */

/** Color key (a layer's legend color, or one the styles below use) -> its CSS variable. */
export const TOKENS = {
  nfhl: "--c-nfhl", firm: "--c-firm", drain: "--c-drain", infra: "--c-infra", city: "--c-city",
  hdrain: "--c-hdrain", bridge: "--c-bridge", mapped: "--c-mapped", photos: "--c-photos", fema: "--c-fema",
  nws: "--c-nws", proj: "--c-proj", sfp: "--c-sfp", claims: "--c-claims", county: "--county", dam: "--c-dam",
  "sev-high": "--sev-high", "sev-mod": "--sev-mod", "sev-low": "--sev-low", "sev-unc": "--sev-unc",
  warn: "--warn", bg: "--bg",
  r1: "--r1", r2: "--r2", r3: "--r3", r4: "--r4", r5: "--r5",
};

/** Token key -> its current color. */
export function readColors() {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(Object.entries(TOKENS).map(([key, name]) => [key, style.getPropertyValue(name).trim()]));
}

const POLYGONS = ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]];
const LINES = ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString", "Polygon", "MultiPolygon"]]];
const POINTS = ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]];

/** A hazard zone's color by its relative severity: severe red, moderate orange, light blue. */
const bySeverity = (colors) => [
  "match", ["get", "relative_class"],
  "high", colors["sev-high"], "moderate", colors["sev-mod"], "low", colors["sev-low"], colors["sev-unc"],
];

function pointPaint(shape, color, colors) {
  const base = { "circle-color": color, "circle-radius": 4, "circle-stroke-color": colors.bg, "circle-stroke-width": 1 };
  switch (shape) {
    case "fema":
      return { ...base, "circle-radius": 9, "circle-stroke-width": 2 };
    case "ring":
    case "sq":
    case "dia":
      return { ...base, "circle-color": colors.bg, "circle-stroke-color": color, "circle-stroke-width": 1.6, "circle-radius": 3.5 };
    default:
      return base;
  }
}

/** The style layers for one layer (`info` from /api/v1/layers). */
export function styleLayersFor(info, colors) {
  const { shape, color: key } = info.legend;
  const color = colors[key] || colors.nfhl;
  const source = `src-${info.id}`;
  const sourceLayer = info.delivery === "tiles" ? { "source-layer": info.id } : {};
  const at = (suffix, type, filter, paint, layout = {}) => ({
    id: `lyr-${info.id}-${suffix}`, type, source, ...sourceLayer, filter, paint, layout,
  });

  if (info.id === "county-boundaries") {
    return [at("line", "line", LINES, { "line-color": colors.county, "line-width": 1.2, "line-opacity": 0.8 })];
  }
  if (shape === "sev") {
    // The 1981 FIRM is a historic map: dashed outlines tell it apart from current ones.
    const dashed = info.id === "hidalgo-firm-1981" ? { "line-dasharray": [3, 2] } : {};
    return [
      at("fill", "fill", POLYGONS, { "fill-color": bySeverity(colors), "fill-opacity": 0.3 }),
      at("line", "line", LINES, { "line-color": bySeverity(colors), "line-width": 1, "line-opacity": 0.8, ...dashed }),
    ];
  }
  if (info.id === "nfip-claims-by-tract") {
    const ramp = ["match", ["get", "claims_class"], 1, colors.r1, 2, colors.r2, 3, colors.r3, 4, colors.r4, colors.r5];
    return [at("fill", "fill", POLYGONS, { "fill-color": ramp, "fill-opacity": 0.72 })];
  }
  if (info.id === "hcdd1-flood-photos") {
    const openable = ["has", "photo_url"];
    return [at("point", "circle", POINTS, {
      "circle-color": color,
      "circle-radius": ["case", openable, 3.4, 2.2],
      "circle-stroke-color": colors.bg,
      "circle-stroke-width": ["case", openable, 1, 0],
      "circle-opacity": 0.9,
    })];
  }

  const layers = [];
  if (shape === "poly") layers.push(at("fill", "fill", POLYGONS, { "fill-color": color, "fill-opacity": 0.5 }));
  layers.push(at("line", "line", LINES, { "line-color": color, "line-width": shape === "line" ? 1.4 : 1 }));
  layers.push(at("point", "circle", POINTS, pointPaint(shape, color, colors)));
  return layers;
}
