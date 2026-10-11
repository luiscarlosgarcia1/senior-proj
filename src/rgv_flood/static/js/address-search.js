/* Header address search, geocoded client-side through OpenStreetMap Nominatim
 * (the Flask server makes no outbound requests). */

import { fetchJson } from "./fetch-json.js";
import { escapeHtml } from "./html.js";

/** The best match inside `bbox` (west, south, east, north), or null. */
async function geocode(query, bbox) {
  const params = new URLSearchParams({
    format: "jsonv2",
    limit: "1",
    countrycodes: "us",
    viewbox: bbox.join(","),
    bounded: "1",
    q: query,
  });
  const hits = await fetchJson(`https://nominatim.openstreetmap.org/search?${params}`, {
    headers: { Accept: "application/json" },
  });
  return hits?.[0] ?? null;
}

export function initAddressSearch(map, { bbox }) {
  const form = document.getElementById("addr-search");
  let marker = null;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = form.q.value.trim();
    if (!query) return;

    form.classList.remove("not-found");
    const hit = await geocode(query, bbox);
    if (!hit) {
      form.classList.add("not-found");
      return;
    }
    const latlng = [parseFloat(hit.lat), parseFloat(hit.lon)];
    marker?.remove();
    marker = L.marker(latlng).addTo(map).bindPopup(`<strong>${escapeHtml(hit.display_name)}</strong>`).openPopup();
    map.flyTo(latlng, 14);
  });
}
