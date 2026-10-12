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

/** The photo itself, where the district publishes it: a small version from the
 * district's server, linked to the full-size original. */
function photo(p) {
  if (!p.photo_url) return `${note("The district has not published the image for this photo.")}<br>`;
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

const POPUPS = {
  flood_extent: (p) =>
    `<strong>Mapped flooding — ${esc(p.year)}</strong><br>` +
    `District label for this event: ${esc(p.hcdd1_label)}<br>` +
    note(`${esc(p.source)}. The label is the district's own; whether it is rainfall or flood depth isn't stated.`),

  flood_photo: (p) =>
    `<strong>Flood response photo</strong><br>${esc(p.event)}<br>` +
    (p.taken ? `Taken ${esc(p.taken)}<br>` : "") +
    photo(p) +
    note(`${HCDD1}. Shows where crews documented conditions, not necessarily standing water.`),

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
