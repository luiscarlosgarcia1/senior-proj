/* NOAA flood events: a filterable list and the selected event's detail
 * (rain at the nearest gauges, curated reports, NWS flood reports). Selecting
 * an event with a point flies the map there and rings it. */

import { getJson, isAbort } from "../api.js";
import { mapReady } from "../map/main.js";
import { select } from "../map/popups.js";
import { day, eventSeverity } from "./format.js";

const RECENT_YEARS = 5;

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.store("events", {
    selectedId: null,
    context: null,
    showTable: false,
    /** Clear the selection: no ring, no detail card. */
    clear() {
      this.selectedId = null;
      this.context = null;
      select(null);
    },
    /** Select an event: fly to it (when it has a point), ring it, load its context.
     * Picking the selected event again clears it. */
    async open(event) {
      if (this.selectedId === event.id) return this.clear();
      this.selectedId = event.id;
      this.showTable = false;
      if (event.lat !== null && event.lat !== undefined) {
        const map = await mapReady;
        map.flyTo({ center: [event.lon, event.lat], zoom: 11, duration: 800 });
        select([event.lon, event.lat]);
      }
      try {
        this.context = await getJson(`events/${encodeURIComponent(event.id)}/context`);
      } catch (error) {
        if (!isAbort(error)) console.warn("event context unavailable", error);
      }
    },
    /** Select an event known only by id (from a shared link); unknown ids are ignored. */
    async openById(id, { fly = true } = {}) {
      try {
        const context = await getJson(`events/${encodeURIComponent(id)}/context`);
        this.selectedId = id;
        this.context = context;
        if (fly && context.event.lat !== null) select([context.event.lon, context.event.lat]);
      } catch (error) {
        if (!isAbort(error) && error.status !== 404) console.warn("event unavailable", error);
      }
    },
  });

  Alpine.data("eventsPanel", () => ({
    events: [],
    total: 0,
    types: [],
    years: [],
    chip: "",
    loaded: false,
    init() {
      Alpine.effect(() => this.load(Alpine.store("app").county));
    },
    async load(county = Alpine.store("app").county) {
      const isYear = /^\d{4}$/.test(this.chip);
      try {
        const body = await getJson("events", {
          county, type: isYear ? null : this.chip || null, year: isYear ? this.chip : null,
        });
        Object.assign(this, { events: body.events, total: body.total, types: body.types, years: body.years, loaded: true });
      } catch (error) {
        if (!isAbort(error)) console.warn("events unavailable", error);
      }
    },
    get chips() {
      return [{ id: "", label: "All" }, ...this.types.map((type) => ({ id: type, label: type })),
        ...this.years.slice(0, RECENT_YEARS).map((year) => ({ id: String(year), label: String(year) }))];
    },
    get empty() {
      return this.loaded && this.events.length === 0;
    },
    // inside x-for: `this.c` (chip), `this.event`
    chipClass() {
      return this.chip === this.c.id ? "border-accent text-ink bg-accent-soft" : "";
    },
    pickChip() {
      this.chip = this.c.id;
      this.load();
    },
    title() {
      return `${this.event.type}, ${(this.event.location || "").split(",")[0]}`;
    },
    date() {
      return day(this.event.date);
    },
    dot() {
      return `background: var(--sev-${eventSeverity(this.event.type)})`;
    },
    rowClass() {
      return Alpine.store("events").selectedId === this.event.id ? "is-selected" : "";
    },
    choose() {
      Alpine.store("events").open(this.event);
    },
  }));

  Alpine.data("eventDetail", () => ({
    get context() {
      return Alpine.store("events").context;
    },
    get open() {
      return this.context !== null;
    },
    get heading() {
      const e = this.context.event;
      return `${e.type}, ${(e.location || "").split(",")[0]}, ${day(e.date)}`;
    },
    get subheading() {
      const e = this.context.event;
      return [e.county.charAt(0).toUpperCase() + e.county.slice(1) + " County", "NOAA Storm Events"].join(" · ");
    },
    get beganIndex() {
      return Math.max(0, this.context.rain.days.findIndex((d) => d.began));
    },
    get bars() {
      const index = this.beganIndex;
      const values = this.context.rain.gauges.map((g) => g.inches[index] ?? 0);
      const top = Math.max(...values, 0.01);
      return this.context.rain.gauges.map((gauge, i) => ({
        id: `${gauge.name}-${i}`,
        name: gauge.name,
        value: gauge.inches[index] == null ? "—" : gauge.inches[index].toFixed(2),
        height: `height: ${Math.round((values[i] / top) * 54)}px`,
        distance: gauge.distance_km == null ? "" : `${gauge.distance_km} km`,
      }));
    },
    get days() {
      return this.context.rain.days;
    },
    get showTable() {
      return Alpine.store("events").showTable;
    },
    toggleTable() {
      Alpine.store("events").showTable = !Alpine.store("events").showTable;
    },
    // inside x-for: `this.gauge`, `this.report`, `this.nws`
    cells() {
      return this.gauge.inches.map((value, i) => ({ id: i, text: value == null ? "—" : value.toFixed(2) }));
    },
    reportMeta() {
      return [this.report.publisher, day(this.report.event_date)].filter(Boolean).join(" · ");
    },
    nwsMeta() {
      const when = new Date(this.nws.reported_at).toLocaleTimeString("en-US", { timeZone: "America/Chicago", timeStyle: "short" });
      return ["NWS", this.nws.city, when].filter(Boolean).join(" · ");
    },
  }));
});
