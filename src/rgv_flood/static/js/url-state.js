/* Keeps the current view in the page address so it can be bookmarked or sent
 * to someone: the county, which layers are on, whether event points show, and
 * where the map is. For example
 *
 *   #county=hidalgo&layers=fema-nfhl,overture-bridges&events=1&map=26.2034,-98.2300,11
 *
 * Call it after the other modules have attached their listeners: a view is
 * restored by setting the same controls a person would.
 */

/** A `change` event. `keepView` tells the county selector not to move the map,
 * for when the address also says exactly where the map should be. */
const changed = (keepView = false) => new CustomEvent("change", { bubbles: true, detail: { keepView } });

export function initUrlState(map) {
  const county = document.getElementById("county-select");
  const events = document.getElementById("events-toggle");
  const layerBoxes = [...document.querySelectorAll(".layer-toggle")];
  let applying = false;

  function setChecked(box, wanted) {
    if (box.checked === wanted) return;
    box.checked = wanted;
    box.dispatchEvent(changed());
  }

  /** Make the page match the address. */
  function apply() {
    applying = true;
    const saved = new URLSearchParams(location.hash.slice(1));

    const wantedLayers = new Set((saved.get("layers") ?? "").split(",").filter(Boolean));
    for (const box of layerBoxes) setChecked(box, wantedLayers.has(box.value));
    setChecked(events, saved.get("events") === "1");

    const view = (saved.get("map") ?? "").split(",").map(Number);
    const hasView = view.length === 3 && view.every(Number.isFinite);
    if (hasView) map.setView([view[0], view[1]], view[2]);

    const known = [...county.options].some((option) => option.value === saved.get("county"));
    const wantedCounty = known ? saved.get("county") : "";
    if (county.value !== wantedCounty) {
      county.value = wantedCounty;
      county.dispatchEvent(changed(hasView)); // refreshes the side panels; flies there unless a view was given
    }
    applying = false;
  }

  /** Make the address match the page. */
  function write() {
    if (applying) return;
    const center = map.getCenter();
    const state = {
      county: county.value,
      layers: layerBoxes.filter((box) => box.checked).map((box) => box.value).join(","),
      events: events.checked ? "1" : "",
      map: `${center.lat.toFixed(4)},${center.lng.toFixed(4)},${map.getZoom()}`,
    };
    const hash = Object.entries(state)
      .filter(([, value]) => value)
      .map(([key, value]) => `${key}=${value}`)
      .join("&");
    history.replaceState(null, "", `#${hash}`); // replaceState does not fire hashchange
  }

  if (location.hash) apply();
  window.addEventListener("hashchange", apply); // a link pasted into a tab that is already open

  for (const control of [county, events, ...layerBoxes]) control.addEventListener("change", write);
  // The map settles its own size as the page loads; only moves after that are the reader's.
  window.addEventListener("load", () => setTimeout(() => map.on("moveend", write)));
}
