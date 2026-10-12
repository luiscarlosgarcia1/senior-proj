/* Sidebar behavior: one open card at a time, and the county selector's map
 * movement. The county-scoped panels refresh themselves: each one listens for
 * the selector's change event (hx-trigger in index.html). */

import { fetchJson } from "./fetch-json.js";

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
    boundaries ??= fetchJson("/api/layers/county-boundaries.geojson");
    const collection = await boundaries;
    if (!collection) boundaries = null; // retry on the next change
    const county = collection?.features?.find((f) => f.properties?.county_slug === slug);
    return county ? L.geoJSON(county).getBounds() : null;
  }

  select.addEventListener("change", async (e) => {
    if (e.detail?.keepView) return; // a shared link that also says where the map should be (url-state.js)
    if (!select.value) {
      map.flyTo(center, zoom);
      return;
    }
    const bounds = await countyBounds(select.value);
    if (bounds) map.flyToBounds(bounds);
  });
}
