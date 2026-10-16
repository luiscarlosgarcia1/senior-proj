/* Basemap labels on the US side only: the project covers four Texas counties,
 * so Mexican city, road and place names across the Rio Grande are noise.
 * Water names (the Rio Grande, the Laguna Madre) stay. */

// The US north of the four counties, as far as the map is likely to be panned.
const NORTH_OF_COUNTIES = [[[-99.25, 26.8], [-96.0, 26.8], [-96.0, 29.0], [-99.25, 29.0], [-99.25, 26.8]]];

// OpenMapTiles source layers whose labels sit on land.
const LAND_LABELS = new Set(["place", "transportation_name", "poi", "aerodrome_label", "housenumber"]);

/** The area labels may show in: the four counties plus the US north of them. */
export function usSideMask(counties) {
  const polygons = counties.features.flatMap(({ geometry }) =>
    geometry.type === "Polygon" ? [geometry.coordinates] : geometry.type === "MultiPolygon" ? geometry.coordinates : []);
  return { type: "MultiPolygon", coordinates: [...polygons, NORTH_OF_COUNTIES] };
}

/** The style's layers with land labels limited to the mask; other layers unchanged. */
export function hideForeignLabels(layers, mask) {
  const within = ["within", mask];
  return layers.map((layer) => {
    if (layer.type !== "symbol" || !LAND_LABELS.has(layer["source-layer"])) return layer;
    return { ...layer, filter: layer.filter ? ["all", layer.filter, within] : within };
  });
}
