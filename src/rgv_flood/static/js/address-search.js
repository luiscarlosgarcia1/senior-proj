/* Header address search, geocoded client-side through OpenStreetMap Nominatim
 * (the Flask server makes no outbound requests). */

import { escapeHtml } from "./html.js";

// West, south, east, north around the four counties, to bound the search.
const VIEWBOX = "-99.7,25.6,-96.9,27.1";

async function geocode(query) {
  const params = new URLSearchParams({
    format: "jsonv2",
    limit: "1",
    countrycodes: "us",
    viewbox: VIEWBOX,
    bounded: "1",
    q: query,
  });
  const response = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) return null;
  const [hit] = await response.json();
  return hit ?? null;
}

export function initAddressSearch(map) {
  const form = document.getElementById("addr-search");
  let marker = null;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = form.q.value.trim();
    if (!query) return;

    form.classList.remove("not-found");
    const hit = await geocode(query);
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
