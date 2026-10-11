/* Sidebar behavior: one open card at a time, and the county selector, which
 * recenters the map and refreshes the county-scoped panels. (HTMX already
 * refreshes the reports panel through hx-get on the select itself.) */

/** Reload one sidebar panel from a server partial. */
function refreshPanel(target, path, params) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value)).toString();
  // `source` gives each panel its own HTMX request queue. Without it every call
  // shares the page body's queue, which keeps only the last of several requests
  // fired together, silently dropping the others.
  htmx.ajax("GET", query ? `${path}?${query}` : path, { target, source: target });
}

export function initAccordion() {
  const cards = document.querySelectorAll(".sidebar details.collapse");
  cards.forEach((card) => {
    card.addEventListener("toggle", () => {
      if (!card.open) return;
      cards.forEach((other) => {
        if (other !== card) other.open = false;
      });
    });
  });
}

export function initCountySelect(map, { center, zoom }) {
  const select = document.getElementById("county-select");
  let boundaries = null;

  async function countyBounds(slug) {
    boundaries ??= fetch("/api/layers/county-boundaries.geojson").then((r) => (r.ok ? r.json() : null));
    const collection = await boundaries;
    if (!collection) boundaries = null; // retry on the next change
    const county = collection?.features?.find((f) => f.properties?.county_slug === slug);
    return county ? L.geoJSON(county).getBounds() : null;
  }

  select.addEventListener("change", async () => {
    const county_slug = select.value;
    const year = document.getElementById("event-year")?.value;
    refreshPanel("#events-body", "/partials/events", { year, county_slug });
    refreshPanel("#rainfall-body", "/partials/rainfall", { county_slug });
    refreshPanel("#live-signals-body", "/partials/live-signals", { county_slug });

    if (!county_slug) {
      map.flyTo(center, zoom);
      return;
    }
    const bounds = await countyBounds(county_slug);
    if (bounds) map.flyToBounds(bounds);
  });
}
