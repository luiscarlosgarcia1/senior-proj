/* RGV Flood Impact Visualizer — Leaflet map + layer toggles.
 *
 * The map owns spatial state (pan/zoom, which overlays are visible). HTMX owns
 * the server-rendered side panels (source metadata, closure reports).
 */
(function () {
  "use strict";

  const cfg = window.RGV_CONFIG || { center: [26.3, -98.15], zoom: 9 };

  const map = L.map("map").setView(cfg.center, cfg.zoom);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  const SEVERITY_STYLE = {
    high: { color: "#7f1d1d", weight: 1, fillColor: "#dc2626", fillOpacity: 0.35 },
    moderate: { color: "#92400e", weight: 1, fillColor: "#f59e0b", fillOpacity: 0.3 },
    low: { color: "#1e40af", weight: 1, fillColor: "#60a5fa", fillOpacity: 0.2 },
    uncategorized: { color: "#374151", weight: 1, fillColor: "#9ca3af", fillOpacity: 0.25 },
  };

  const loaded = new Map(); // layerId -> L.GeoJSON

  function styleFor(feature) {
    const cls = (feature.properties && feature.properties.relative_class) || "uncategorized";
    return SEVERITY_STYLE[cls] || SEVERITY_STYLE.uncategorized;
  }

  async function showLayer(layerId) {
    if (loaded.has(layerId)) {
      loaded.get(layerId).addTo(map);
      return;
    }
    const res = await fetch(`/api/layers/${layerId}.geojson`);
    if (!res.ok) {
      console.error("layer fetch failed", layerId, res.status);
      return;
    }
    const gj = L.geoJSON(await res.json(), {
      style: styleFor,
      onEachFeature: (feature, lyr) => {
        const p = feature.properties || {};
        lyr.bindPopup(
          `<strong>${p.source || "source"}</strong><br>` +
            `${p.original_category || ""}<br>` +
            `relative class: ${p.relative_class || "uncategorized"}`
        );
      },
    });
    loaded.set(layerId, gj);
    gj.addTo(map);
  }

  function hideLayer(layerId) {
    if (loaded.has(layerId)) map.removeLayer(loaded.get(layerId));
  }

  document.querySelectorAll(".layer-toggle").forEach((box) => {
    box.addEventListener("change", (e) => {
      if (e.target.checked) showLayer(e.target.value);
      else hideLayer(e.target.value);
    });
  });

  // County select also recenters the map (HTMX handles the closures panel).
  const countySelect = document.getElementById("county-select");
  if (countySelect) {
    countySelect.addEventListener("change", async () => {
      const slug = countySelect.value;
      if (!slug) {
        map.setView(cfg.center, cfg.zoom);
        return;
      }
      const res = await fetch(`/api/layers/county-boundaries.geojson`);
      if (!res.ok) return;
      const fc = await res.json();
      const match = (fc.features || []).find(
        (f) => f.properties && f.properties.county_slug === slug
      );
      if (match) map.fitBounds(L.geoJSON(match).getBounds());
    });
  }
})();
