/* Popup HTML for each kind of map feature. Every value from layer data is escaped. */

import { escapeHtml as esc } from "./html.js";

const HCDD1 = "Hidalgo County Drainage District No. 1";
export const PHOTO_WIDTH = 260; // CSS pixels; twice that is requested so it stays sharp on dense screens
const note = (text) => `<span class="popup-note">${text}</span>`;

const DRAINAGE_KINDS = {
  channel: "Drainage channel",
  planned_channel: "Planned channel",
  detention_pond: "Detention pond",
  gate: "Gate",
  pump: "Pump",
};

/** A small version of the photo from the district's server, linked to the
 * full-size original. */
function photo(p) {
  const url = esc(p.photo_url);
  return (
    `<a class="popup-photo" href="${url}" target="_blank" rel="noopener" title="Open the full-size photo">` +
    `<img src="${url}?w=${PHOTO_WIDTH * 2}" alt="District photo, ${esc(p.event)}" loading="lazy"></a>`
  );
}

function yearRange(start, end) {
  if (start && end) return `${start}–${end}`;
  return start ? `started ${start}` : "";
}

const TWDB = "Texas Water Development Board, 2024 State Flood Plan";
const dollars = (n) => `$${Math.round(n).toLocaleString()}`;

const WATERWAY_KINDS = {
  drain: "Drain or floodway",
  resaca: "Resaca",
  canal: "Irrigation canal",
  canal_or_ditch: "Canal or ditch",
  creek: "Creek or arroyo",
};
const FLOOD_WORK_KINDS = {
  dam: "Dam",
  levee: "Levee",
  sea_wall: "Sea wall",
  storm_drain: "Storm drain system",
  pond: "Pond",
  low_water_crossing: "Low-water crossing",
  other: "Flood infrastructure",
};
const CITY_DRAINAGE_KINDS = { ditch: "Drainage ditch", storm_sewer: "Storm sewer", detention_pond: "Detention pond" };
const REPORT_KINDS = {
  flash_flood: "Flash flood",
  flood: "Flood",
  heavy_rain: "Heavy rain",
  coastal_flood: "Coastal flood",
};

/** A UTC timestamp as the time it was in the valley. */
function valleyTime(iso) {
  return new Date(iso).toLocaleString("en-US", { timeZone: "America/Chicago", dateStyle: "medium", timeStyle: "short" });
}

function floodProjectFacts(p) {
  if (p.stage === "ongoing") {
    return [p.cost ? `Cost ${dollars(p.cost)}` : "", p.funding ? `funded by ${esc(p.funding)}` : "", p.year ? `due ${esc(p.year)}` : ""];
  }
  const buildings =
    p.structures_at_risk != null
      ? `Buildings in the 100-year floodplain: ${p.structures_at_risk.toLocaleString()} now, ` +
        `${(p.structures_still_at_risk ?? 0).toLocaleString()} after`
      : "";
  return [esc(p.project_type || ""), p.cost ? `estimated ${dollars(p.cost)}` : "", buildings];
}

const POPUPS = {
  waterway: (p) => {
    const kind = WATERWAY_KINDS[p.kind] || "Waterway";
    return (
      `<strong>${esc(p.name || kind)}</strong><br>${kind} · ${esc(p.county)} County<br>` +
      note("U.S. Census Bureau water lines. The kind is read from the line's own name.")
    );
  },

  flood_infrastructure: (p) => {
    const kind = FLOOD_WORK_KINDS[p.kind] || "Flood infrastructure";
    return (
      `<strong>${esc(p.name || kind)}</strong><br>${kind} · ${esc(p.county)} County` +
      (p.description && p.description !== p.name ? `<br>${esc(p.description)}` : "") +
      (p.condition ? `<br>Condition: ${esc(p.condition)}` : "") +
      `<br>${note(TWDB)}`
    );
  },

  flood_project: (p) => {
    const stage = p.stage === "ongoing" ? "Ongoing project" : "Recommended in the state flood plan";
    const facts = floodProjectFacts(p).filter(Boolean);
    return (
      `<strong>${esc(p.name || "Flood project")}</strong><br>${stage} · ${esc(p.county)} County` +
      (facts.length ? `<br>${facts.join(" · ")}` : "") +
      (p.description ? `<br><br>${esc(p.description)}` : "") +
      `<br>${note(TWDB)}`
    );
  },

  city_drainage: (p) => {
    const kind = CITY_DRAINAGE_KINDS[p.kind] || "Drainage";
    const pipe = [p.size, p.material].filter(Boolean).map(esc).join(" ");
    return (
      `<strong>${esc(p.name || kind)}</strong><br>${kind} · ${esc(p.city)}` +
      (p.owner ? `<br>Owner: ${esc(p.owner)}` : "") +
      (pipe ? `<br>Pipe: ${pipe}` : "") +
      `<br>${note(`City of ${esc(p.city)}`)}`
    );
  },

  storm_report: (p) =>
    `<strong>${REPORT_KINDS[p.kind] || "Flood"} report</strong><br>` +
    `${esc(valleyTime(p.reported_at))}${p.city ? ` · ${esc(p.city)}` : ""}, ${esc(p.county)} County` +
    (p.magnitude ? `<br>Rain reported: ${esc(p.magnitude)} in` : "") +
    (p.remark ? `<br><br>${esc(p.remark)}` : "") +
    `<br>${note(`Reported to NWS Brownsville${p.source ? ` by: ${esc(p.source)}` : ""}`)}`,

  flood_extent: (p) =>
    `<strong>Mapped flooding — ${esc(p.year)}</strong><br>` +
    `District label for this event: ${esc(p.hcdd1_label)}<br>` +
    note(`${esc(p.source)}. The label is the district's own; whether it is rainfall or flood depth isn't stated.`),

  // The district publishes the image for some photos and only where and when
  // it was taken for the rest. They are named differently so neither misleads.
  flood_photo: (p) =>
    p.photo_url
      ? `<strong>Flood photo</strong><br>${esc(p.event)}<br>` +
        (p.taken ? `Taken ${esc(p.taken)}<br>` : "") +
        photo(p) +
        note(`${HCDD1}. Shows where crews documented conditions, not necessarily standing water.`)
      : `<strong>Photo location</strong><br>${esc(p.event)}<br>` +
        (p.taken ? `Photo taken ${esc(p.taken)}<br>` : "") +
        note(`A crew from ${HCDD1} photographed conditions here. The district has not published the image.`),

  drainage: (p) => {
    const detail = p.acres ? `${p.acres} acres` : esc(p.owner);
    return (
      `<strong>${esc(p.name)}</strong><br>${DRAINAGE_KINDS[p.kind] || "Drainage"}` +
      (detail ? ` · ${detail}` : "") +
      `<br>${note(HCDD1)}`
    );
  },

  bond_project: (p) => {
    const facts = [p.program, p.status, yearRange(p.start_year, p.end_year)].filter(Boolean).map(esc);
    return (
      `<strong>${esc(p.name)}</strong><br>${facts.join(" · ")}` +
      (p.description ? `<br><br>${esc(p.description)}` : "") +
      `<br>${note(HCDD1)}`
    );
  },

  claims: (p) => {
    const years = p.first_year && p.last_year ? `${p.first_year}–${p.last_year}` : "none on record";
    const moved = p.from_old_tracts
      ? ` About ${p.from_old_tracts.toLocaleString()} were filed under older tract boundaries and are spread across the tracts that replaced them.`
      : "";
    return (
      `<strong>${p.claims.toLocaleString()} flood insurance claim${p.claims === 1 ? "" : "s"}</strong><br>` +
      `Tract ${esc(p.geoid)} · ${esc(p.county)} County<br>` +
      `Paid: $${Number(p.paid).toLocaleString()} · years: ${years}` +
      (p.top_event ? `<br>Most common event: ${esc(p.top_event)}` : "") +
      `<br>${note(`FEMA NFIP claims. Raw counts, not adjusted for how many homes are insured.${moved}`)}`
    );
  },
};

function infrastructurePopup(p) {
  const kind = p.infrastructure_type === "dam" ? "Dam" : "Bridge";
  return (
    `<strong>${esc(p.name || kind)}</strong><br>${kind} · ${esc(p.county || "—")} County<br>` +
    note("Source: Overture Maps Foundation (OpenStreetMap)")
  );
}

function hazardPopup(p) {
  return (
    `<strong>${esc(p.source || "source")}</strong><br>` +
    `zone: ${esc(p.original_category || "—")}<br>` +
    `relative severity: ${esc(p.relative_class || "uncategorized")}`
  );
}

/** HTML for a feature's popup, chosen from its properties. */
export function popupHtml(p) {
  if (p.original_category === "county boundary") return `<strong>${esc(p.county || "County")}</strong>`;
  if (p.overlay_type) return POPUPS[p.overlay_type]?.(p) ?? null;
  if (p.infrastructure_type) return infrastructurePopup(p);
  return hazardPopup(p);
}
