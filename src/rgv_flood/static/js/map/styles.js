/* How each layer looks on the map, as MapLibre style layers.
 *
 * Every layer gets up to three style layers, one per kind of geometry:
 * `lyr-<id>-fill` (polygons), `lyr-<id>-line` (lines and polygon outlines) and
 * `lyr-<id>-point`. Colors come from the design tokens (the CSS variables in
 * input.css), so a theme switch only needs `readColors()` again. */

const TOKENS = {
  nfhl: "--c-nfhl", firm: "--c-firm", twdb: "--c-twdb", drain: "--c-drain", infra: "--c-infra", city: "--c-city",
  hdrain: "--c-hdrain", bridge: "--c-bridge", mapped: "--c-mapped", photos: "--c-photos", fema: "--c-fema",
  nws: "--c-nws", proj: "--c-proj", sfp: "--c-sfp", claims: "--c-claims", county: "--county",
  "sev-high": "--sev-high", warn: "--warn", bg: "--bg", panel: "--panel", brand: "--brand",
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

// Hazard zones: stronger fill for the more severe classes.
const BY_SEVERITY = ["match", ["get", "relative_class"], "high", 0.38, "moderate", 0.24, "low", 0.14, 0.2];

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
  if (shape === "poly" || shape === "ramp") {
    const opacity = info.id === "hcdd1-flood-extents" ? 0.5 : BY_SEVERITY;
    layers.push(at("fill", "fill", POLYGONS, { "fill-color": color, "fill-opacity": opacity }));
  }
  const dashed = shape === "dash" ? { "line-dasharray": [3, 2] } : {};
  const width = shape === "line" ? 1.4 : 1;
  layers.push(at("line", "line", LINES, { "line-color": color, "line-width": width, ...dashed }));
  layers.push(at("point", "circle", POINTS, pointPaint(shape, color, colors)));
  return layers;
}
