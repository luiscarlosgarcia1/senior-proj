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

  // Infrastructure (bridges/dams) isn't a hazard rating, so it gets its own
  // colors, distinct from the severity palette above (see app.css --infra-*).
  const INFRA_STYLE = {
    bridge: { color: "#7c3aed", weight: 2, fillColor: "#7c3aed", fillOpacity: 0.35 },
    dam: { color: "#0d9488", weight: 1, fillColor: "#0d9488", fillOpacity: 0.45 },
  };

  // Stacking order is fixed by pane, not by toggle order: hazard polygons
  // (overlay pane, 400) < flood-response photos (430) < flood-event dots (480).
  map.createPane("evidence").style.zIndex = 430;
  map.createPane("events").style.zIndex = 480;
  // ~18k photo points: canvas, not SVG, or panning would crawl.
  const evidenceCanvas = L.canvas({ pane: "evidence", padding: 0.5 });

  // Flood evidence, drainage and claims overlays (Hidalgo drainage district,
  // FEMA NFIP). Colors are chosen to stay apart from the severity palette.
  const OVERLAY = {
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

  const OVERLAY_LEGENDS = {
    "hcdd1-flood-extents": [{ shape: "square", color: "#1e6bb8", label: "Mapped flooding" }],
    "hcdd1-flood-photos": [{ shape: "dot", color: "#0f172a", label: "Flood response photo" }],
    "hcdd1-drainage": [
      { shape: "line", color: "#475569", label: "Channel" },
      { shape: "dash", color: "#475569", label: "Planned channel" },
      { shape: "square", color: "#38bdf8", label: "Detention pond" },
      { shape: "ring", color: "#0e7490", label: "Gate" },
      { shape: "dot", color: "#be123c", label: "Pump" },
    ],
    "hcdd1-bond-projects": Object.entries(BOND_STATUS_COLORS).map(([label, color]) => ({
      shape: "square",
      color,
      label: `Project: ${label.toLowerCase()}`,
    })),
    "nfip-claims-by-tract": [
      { ramp: CLAIMS_RAMP.slice(1), label: "Insurance claims per tract (fewer → more)" },
    ],
  };

  function legendRow(item) {
    if (item.ramp) {
      const cells = item.ramp
        .map((c) => `<span class="lg lg-ramp" style="background:${c}"></span>`)
        .join("");
      return `<li class="lg-ramp-row"><span class="lg-ramp-cells">${cells}</span>${escapeHtml(item.label)}</li>`;
    }
    const style =
      item.shape === "line" || item.shape === "dash"
        ? `border-top-color:${item.color}`
        : item.shape === "ring"
          ? `border-color:${item.color}`
          : `background:${item.color}`;
    return `<li><span class="lg lg-${item.shape}" style="${style}"></span>${escapeHtml(item.label)}</li>`;
  }

  function renderOverlayLegend() {
    const box = document.getElementById("overlay-legend");
    if (!box) return;
    const rows = [];
    document.querySelectorAll(".layer-toggle:checked").forEach((input) => {
      (OVERLAY_LEGENDS[input.value] || []).forEach((item) => rows.push(legendRow(item)));
    });
    box.hidden = rows.length === 0;
    box.innerHTML = rows.length ? `<ul class="overlay-legend-list">${rows.join("")}</ul>` : "";
  }

  function overlayPopup(p) {
    const county = p.county ? ` · ${escapeHtml(p.county)} County` : "";
    switch (p.overlay_type) {
      case "flood_extent":
        return (
          `<strong>Mapped flooding — ${escapeHtml(p.year)}</strong><br>` +
          `District label for this event: ${escapeHtml(p.hcdd1_label)}<br>` +
          `<span class="popup-note">${escapeHtml(p.source)}. The label is the district's own; ` +
          `whether it is rainfall or flood depth isn't stated.</span>`
        );
      case "flood_photo":
        return (
          `<strong>Flood response photo</strong><br>${escapeHtml(p.event)}<br>` +
          (p.taken ? `Taken ${escapeHtml(p.taken)}<br>` : "") +
          `<span class="popup-note">Hidalgo County Drainage District No. 1. Shows where crews ` +
          `documented conditions, not necessarily standing water.</span>`
        );
      case "drainage": {
        const kinds = {
          channel: "Drainage channel",
          planned_channel: "Planned channel",
          detention_pond: "Detention pond",
          gate: "Gate",
          pump: "Pump",
        };
        const extra = p.acres ? `${p.acres} acres` : p.owner ? escapeHtml(p.owner) : "";
        return (
          `<strong>${escapeHtml(p.name)}</strong><br>${kinds[p.kind] || "Drainage"}` +
          (extra ? ` · ${extra}` : "") +
          `<br><span class="popup-note">Hidalgo County Drainage District No. 1</span>`
        );
      }
      case "bond_project": {
        const years =
          p.start_year && p.end_year
            ? `${p.start_year}–${p.end_year}`
            : p.start_year
              ? `started ${p.start_year}`
              : "";
        return (
          `<strong>${escapeHtml(p.name)}</strong><br>${escapeHtml(p.program)}` +
          (p.status ? ` · ${escapeHtml(p.status)}` : "") +
          (years ? ` · ${years}` : "") +
          (p.description ? `<br><br>${escapeHtml(p.description)}` : "") +
          `<br><span class="popup-note">Hidalgo County Drainage District No. 1</span>`
        );
      }
      case "claims": {
        const years =
          p.first_year && p.last_year ? `${p.first_year}–${p.last_year}` : "none on record";
        return (
          `<strong>${p.claims.toLocaleString()} flood insurance claim${p.claims === 1 ? "" : "s"}</strong>` +
          `<br>Tract ${escapeHtml(p.geoid)}${county}<br>` +
          `Paid: $${Number(p.paid).toLocaleString()} · years: ${years}` +
          (p.top_event ? `<br>Most common event: ${escapeHtml(p.top_event)}` : "") +
          `<br><span class="popup-note">FEMA NFIP claims. Raw counts, not adjusted for how many ` +
          `homes are insured.` +
          (p.from_old_tracts
            ? ` About ${p.from_old_tracts.toLocaleString()} were filed under older tract ` +
              `boundaries and are spread across the tracts that replaced them.`
            : "") +
          `</span>`
        );
      }
      default:
        return null;
    }
  }

  function styleFor(feature) {
    const p = feature.properties || {};
    if (p.original_category === "county boundary") return BOUNDARY_STYLE;
    if (p.infrastructure_type) return INFRA_STYLE[p.infrastructure_type] || INFRA_STYLE.bridge;
    switch (p.overlay_type) {
      case "flood_extent":
        return OVERLAY.extent;
      case "drainage":
        return OVERLAY[p.kind] || OVERLAY.channel;
      case "bond_project": {
        const c = BOND_STATUS_COLORS[p.status] || "#94a3b8";
        return { color: c, weight: 1.2, fillColor: c, fillOpacity: 0.35 };
      }
      case "claims": {
        const cls = p.claims_class || 0;
        return { color: "#b08aa0", weight: 0.6, fillColor: CLAIMS_RAMP[cls], fillOpacity: cls ? 0.5 : 0 };
      }
    }
    return SEVERITY_STYLE[p.relative_class] || SEVERITY_STYLE.uncategorized;
  }

  function infraPointToLayer(feature, latlng) {
    const p = feature.properties || {};
    if (p.overlay_type === "flood_photo") {
      return L.circleMarker(latlng, { ...OVERLAY.photo, pane: "evidence", renderer: evidenceCanvas });
    }
    if (p.overlay_type === "drainage") {
      return L.circleMarker(latlng, OVERLAY[p.kind] || OVERLAY.gate);
    }
    const style = INFRA_STYLE[p.infrastructure_type] || INFRA_STYLE.bridge;
    return L.circleMarker(latlng, { radius: 5, ...style });
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
      pointToLayer: infraPointToLayer,
      onEachFeature: (feature, lyr) => {
        const p = feature.properties || {};
        if (p.original_category === "county boundary") {
          lyr.bindPopup(`<strong>${p.county || "County"}</strong>`);
          return;
        }
        if (p.overlay_type) {
          const html = overlayPopup(p);
          if (p.overlay_type === "flood_photo") {
            lyr.on("click", (e) => L.popup().setLatLng(e.latlng).setContent(html).openOn(map));
          } else if (html) {
            lyr.bindPopup(html, { maxHeight: 240 });
          }
          return;
        }
        if (p.infrastructure_type) {
          const kind = p.infrastructure_type === "dam" ? "Dam" : "Bridge";
          lyr.bindPopup(
            `<strong>${p.name || kind}</strong><br>` +
              `${kind} · ${p.county || "—"} County<br>` +
              `<span class="popup-note">Source: Overture Maps Foundation (OpenStreetMap)</span>`
          );
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
      renderOverlayLegend();
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
                pane: "events",
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

  // ---- active official signals ---------------------------------------------
  //
  // The server projects only active, official signals with source-supplied
  // geometry. Unmappable official notices stay in the sidebar as links.
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  let liveSignalsLayer = null;

  function liveSignalStyle(feature) {
    const source = feature.properties?.source || "";
    if (source.startsWith("drivetexas:")) return { color: "#9a3412", weight: 4 };
    return { color: "#7c3aed", weight: 2, fillColor: "#a78bfa", fillOpacity: 0.2 };
  }

  function liveSignalPopup(properties) {
    const sourceUrl = properties.source_url ? ` <a href="${escapeHtml(properties.source_url)}" target="_blank" rel="noopener">Source</a>` : "";
    const retrieved = properties.retrieved_at ? `<br>Retrieved ${escapeHtml(properties.retrieved_at)}` : "";
    return `<strong>${escapeHtml(properties.summary)}</strong><br>${escapeHtml(properties.source_publisher)}${retrieved}${sourceUrl}`;
  }

  async function loadLiveSignals() {
    const response = await fetch("/api/live-signals.geojson");
    if (!response.ok) return;
    liveSignalsLayer = L.geoJSON(await response.json(), {
      style: liveSignalStyle,
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, { ...liveSignalStyle(feature), radius: 7, fillOpacity: 0.75 }),
      onEachFeature: (feature, layer) => layer.bindPopup(liveSignalPopup(feature.properties || {})),
    }).addTo(map);
    liveSignalsLayer.bringToFront();
  }

  loadLiveSignals().catch((error) => console.error("live signal fetch failed", error));

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
        window.htmx.ajax(
          "GET",
          slug ? `/partials/live-signals?county_slug=${slug}` : "/partials/live-signals",
          "#live-signals-body"
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
