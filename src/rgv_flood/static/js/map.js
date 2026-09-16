/* RGV Flood Impact Visualizer — Leaflet map.
 *
 * The map owns spatial state (pan/zoom, which overlays are visible). HTMX owns
 * the server-rendered side panels (source metadata, event list, reports).
 */
(function () {
  "use strict";

  const cfg = window.RGV_CONFIG || { center: [26.3, -98.15], zoom: 9 };

  const map = L.map("map").setView(cfg.center, cfg.zoom);

  // The map container is sized by flexbox; measure it once layout has settled.
  requestAnimationFrame(() => map.invalidateSize());
  window.addEventListener("load", () => map.invalidateSize());

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // ---- hazard layers ---------------------------------------------------------

  // Fill colors match the sidebar legend swatches (see app.css --sev-*).
  const SEVERITY_STYLE = {
    high: { color: "#a83232", weight: 1, fillColor: "#d64545", fillOpacity: 0.38 },
    moderate: { color: "#b06d22", weight: 1, fillColor: "#e0913a", fillOpacity: 0.34 },
    low: { color: "#3f68a8", weight: 1, fillColor: "#5b8bd6", fillOpacity: 0.28 },
    uncategorized: { color: "#7c8296", weight: 1, fillColor: "#aeb3c2", fillOpacity: 0.25 },
  };
  const BOUNDARY_STYLE = { color: "#1b2a4a", weight: 1.5, fill: false, dashArray: "3 3" };

  function styleFor(feature) {
    const p = feature.properties || {};
    if (p.original_category === "county boundary") return BOUNDARY_STYLE;
    return SEVERITY_STYLE[p.relative_class] || SEVERITY_STYLE.uncategorized;
  }

  const loadedLayers = new Map(); // layerId -> L.GeoJSON

  // Flood-event dots must stay clickable no matter what order layers are
  // toggled in -- always render above every hazard layer. Call this right
  // after adding any hazard layer to the map.
  function keepEventsOnTop() {
    if (eventsLayer && map.hasLayer(eventsLayer)) eventsLayer.bringToFront();
  }

  async function showLayer(layerId) {
    if (loadedLayers.has(layerId)) {
      loadedLayers.get(layerId).addTo(map);
      keepEventsOnTop();
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
        if (p.original_category === "county boundary") {
          lyr.bindPopup(`<strong>${p.county || "County"}</strong>`);
          return;
        }
        lyr.bindPopup(
          `<strong>${p.source || "source"}</strong><br>` +
            `zone: ${p.original_category || "—"}<br>` +
            `relative severity: ${p.relative_class || "uncategorized"}`
        );
      },
    });
    loadedLayers.set(layerId, gj);
    gj.addTo(map);
    keepEventsOnTop();
  }

  function hideLayer(layerId) {
    if (loadedLayers.has(layerId)) map.removeLayer(loadedLayers.get(layerId));
  }

  document.querySelectorAll(".layer-toggle").forEach((box) => {
    box.addEventListener("change", (e) => {
      if (e.target.checked) showLayer(e.target.value);
      else hideLayer(e.target.value);
    });
  });

  // ---- documented flood events (points) ------------------------------------

  let eventsLayer = null;
  let eventsLoading = null;

  function eventPopup(p) {
    const span = p.date_end && p.date_end !== p.date ? `${p.date} – ${p.date_end}` : p.date;
    return (
      `<strong>${p.type} — ${span}</strong><br>${p.location}<br><br>` +
      `${p.summary || ""}` +
      (p.source_url
        ? `<br><br><a href="${p.source_url}" target="_blank" rel="noopener">NOAA Storm Events record</a>`
        : "")
    );
  }

  async function ensureEventsLayer() {
    if (eventsLayer) return eventsLayer;
    if (!eventsLoading) {
      eventsLoading = fetch("/api/flood-events.geojson")
        .then((r) => (r.ok ? r.json() : null))
        .then((fc) => {
          if (!fc) return null;
          eventsLayer = L.geoJSON(fc, {
            pointToLayer: (f, latlng) =>
              L.circleMarker(latlng, {
                radius: 5,
                color: "#854d0e",
                weight: 1,
                fillColor: "#eab308",
                fillOpacity: 0.85,
              }),
            onEachFeature: (f, lyr) =>
              lyr.bindPopup(eventPopup(f.properties || {}), { maxHeight: 220 }),
          });
          return eventsLayer;
        });
    }
    return eventsLoading;
  }

  async function setEventsVisible(visible) {
    const layer = await ensureEventsLayer();
    if (!layer) return;
    if (visible) {
      layer.addTo(map);
      layer.bringToFront();
    } else {
      map.removeLayer(layer);
    }
  }

  // The checkbox lives outside the HTMX-swapped list, so a plain listener is fine.
  const eventsToggle = document.getElementById("events-toggle");
  if (eventsToggle) {
    eventsToggle.addEventListener("change", (e) => setEventsVisible(e.target.checked));
  }

  function openEventPopup(id) {
    if (!eventsLayer) return;
    eventsLayer.eachLayer((l) => {
      if (l.feature && l.feature.properties && l.feature.properties.id === id) l.openPopup();
    });
  }

  // Click a list row -> show the layer, fly to the point, open its popup.
  document.addEventListener("click", async (e) => {
    const item = e.target.closest(".event-item.locatable");
    if (!item) return;
    const lat = parseFloat(item.dataset.lat);
    const lon = parseFloat(item.dataset.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    if (eventsToggle && !eventsToggle.checked) {
      eventsToggle.checked = true;
      await setEventsVisible(true);
    } else {
      await ensureEventsLayer();
    }
    map.flyTo([lat, lon], 13);
    map.once("moveend", () => openEventPopup(item.dataset.id));
  });

  // ---- address search -----------------------------------------------------

  // W,S,E,N box around the four RGV counties, used to bias / bound geocoding.
  const RGV_VIEWBOX = "-99.7,25.6,-96.9,27.1";
  let addrMarker = null;

  async function geocode(query) {
    const url =
      "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=us" +
      `&viewbox=${RGV_VIEWBOX}&bounded=1&q=${encodeURIComponent(query)}`;
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const hits = await res.json();
    return hits[0] || null;
  }

  const addrForm = document.getElementById("addr-search");
  if (addrForm) {
    addrForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const query = addrForm.q.value.trim();
      if (!query) return;
      addrForm.classList.remove("not-found");
      const hit = await geocode(query);
      if (!hit) {
        addrForm.classList.add("not-found");
        return;
      }
      const latlng = [parseFloat(hit.lat), parseFloat(hit.lon)];
      if (addrMarker) addrMarker.remove();
      addrMarker = L.marker(latlng)
        .addTo(map)
        .bindPopup(`<strong>${hit.display_name}</strong>`)
        .openPopup();
      map.flyTo(latlng, 14);
    });
  }

  // ---- active weather alerts (NWS, client-side, no server round trip) ------
  //
  // Fetched straight from the browser, like the address search -- the Flask
  // server makes no outbound requests of its own (see README). NWS's alerts
  // API needs no key and allows CORS from anywhere. Polled every 5 minutes;
  // county filtering is done client-side against the already-fetched alerts,
  // no refetch needed when the county selector changes.

  const NWS_ALERTS_URL = "https://api.weather.gov/alerts/active?area=TX";
  const ALERT_POLL_MS = 5 * 60 * 1000;
  // Keep in sync with rgv_flood.counties.COUNTIES. NWS areaDesc spells these
  // as forecast-zone names ("Southern Hidalgo", "Inland Cameron", ...), so a
  // plain substring match against the county name is what actually works.
  const RGV_COUNTY_NAMES = { cameron: "Cameron", hidalgo: "Hidalgo", starr: "Starr", willacy: "Willacy" };
  let activeAlerts = [];

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function formatAlertTime(iso) {
    if (!iso) return "unknown";
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return "unknown";
    return parsed.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function alertMatchesCounty(alertProps, countyName) {
    return (alertProps.areaDesc || "").includes(countyName);
  }

  function alertCounties(areaDesc) {
    return Object.values(RGV_COUNTY_NAMES).filter((name) => (areaDesc || "").includes(name));
  }

  function renderAlertItems(alerts, showCounties) {
    return alerts
      .map(({ properties: p }) => {
        const severity = (p.severity || "unknown").toLowerCase();
        const counties = showCounties ? alertCounties(p.areaDesc) : [];
        return `<li class="alert">
          <details>
            <summary>
              <div class="alert-summary-main">
                <span class="alert-event">${escapeHtml(p.event)}</span>
                ${
                  counties.length
                    ? `<div class="alert-counties">${counties
                        .map((c) => `<span class="alert-county-chip">${escapeHtml(c)}</span>`)
                        .join("")}</div>`
                    : ""
                }
              </div>
              <span class="alert-badge alert-badge-${severity}">${escapeHtml(p.severity || "Unknown")}</span>
            </summary>
            <div class="alert-meta">${escapeHtml(p.areaDesc)}</div>
            <div class="alert-meta">Until ${formatAlertTime(p.expires)} &middot; ${escapeHtml(p.senderName)}</div>
            ${p.description ? `<p class="alert-desc">${escapeHtml(p.description)}</p>` : ""}
            ${p.instruction ? `<p class="alert-instruction">${escapeHtml(p.instruction)}</p>` : ""}
          </details>
        </li>`;
      })
      .join("");
  }

  function renderAlerts(countySlug) {
    const body = document.getElementById("alerts-body");
    const countEl = document.getElementById("alerts-count");
    if (!body) return;

    const names = countySlug ? [RGV_COUNTY_NAMES[countySlug]] : Object.values(RGV_COUNTY_NAMES);
    const relevant = activeAlerts.filter((a) => names.some((name) => alertMatchesCounty(a.properties, name)));

    if (countEl) {
      countEl.hidden = relevant.length === 0;
      countEl.textContent = String(relevant.length);
    }

    if (!relevant.length) {
      const scope = countySlug ? `${names[0]} County` : "the RGV";
      body.innerHTML = `<div class="empty">No active NWS alerts for ${scope} right now.</div>`;
      return;
    }

    // Each alert appears once, tagged with the RGV counties its forecast zone
    // covers — an alert issued for a shared zone (e.g. "Cameron; Willacy")
    // gets one card with both chips, not a duplicate card per county.
    body.innerHTML = `<ul class="alert-list">${renderAlertItems(relevant, !countySlug)}</ul>`;
  }

  async function fetchAlerts() {
    try {
      const res = await fetch(NWS_ALERTS_URL, { headers: { Accept: "application/geo+json" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      activeAlerts = data.features || [];
    } catch (error) {
      console.error("NWS alerts fetch failed", error);
      const body = document.getElementById("alerts-body");
      if (body && !activeAlerts.length) {
        body.innerHTML = '<div class="empty">Couldn’t reach the National Weather Service right now.</div>';
      }
      return;
    }
    renderAlerts(document.getElementById("county-select")?.value || null);
  }

  fetchAlerts();
  setInterval(fetchAlerts, ALERT_POLL_MS);

  // ---- sidebar accordion: opening one card's <details> closes the others ----

  document.querySelectorAll(".sidebar details.collapse").forEach((details) => {
    details.addEventListener("toggle", () => {
      if (!details.open) return;
      document.querySelectorAll(".sidebar details.collapse").forEach((other) => {
        if (other !== details) other.open = false;
      });
    });
  });

  // ---- county selector: recenters the map, and refreshes the events / rainfall
  // panels (HTMX's own hx-get on this element already handles the reports panel) --

  const countySelect = document.getElementById("county-select");
  if (countySelect) {
    countySelect.addEventListener("change", async () => {
      const slug = countySelect.value;

      renderAlerts(slug || null);

      const yearSelect = document.getElementById("event-year");
      const year = yearSelect ? yearSelect.value : "";
      const eventsQuery = new URLSearchParams();
      if (year) eventsQuery.set("year", year);
      if (slug) eventsQuery.set("county_slug", slug);
      if (window.htmx) {
        window.htmx.ajax("GET", `/partials/events?${eventsQuery}`, "#events-body");
        window.htmx.ajax(
          "GET",
          slug ? `/partials/rainfall?county_slug=${slug}` : "/partials/rainfall",
          "#rainfall-body"
        );
      }

      if (!slug) {
        map.flyTo(cfg.center, cfg.zoom);
        return;
      }
      const res = await fetch(`/api/layers/county-boundaries.geojson`);
      if (!res.ok) return;
      const fc = await res.json();
      const match = (fc.features || []).find(
        (f) => f.properties && f.properties.county_slug === slug
      );
      if (match) map.flyToBounds(L.geoJSON(match).getBounds());
    });
  }
})();
