/* The side panel's reference lists: rainfall records, curated local reports,
 * and where the data came from. The first two follow the selected county. */

import { getJson, isAbort } from "../api.js";
import { t } from "../i18n.js";
import { day } from "./format.js";

/** A component that loads one API list and reloads it when the county changes,
 * plus whatever `extra` adds (getters included, so they stay live). */
function countyList(path, extra) {
  const base = {
    items: [],
    loaded: false,
    init() {
      window.Alpine.effect(() => this.load(window.Alpine.store("app").county));
    },
    async load(county) {
      try {
        this.items = await getJson(path, { county: county || null });
        this.loaded = true;
      } catch (error) {
        if (!isAbort(error)) console.warn(`${path} unavailable`, error);
      }
    },
    get empty() {
      return this.loaded && this.items.length === 0;
    },
  };
  return () => Object.defineProperties({}, {
    ...Object.getOwnPropertyDescriptors(base),
    ...Object.getOwnPropertyDescriptors(extra),
  });
}

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("rainfallPanel", countyList("rainfall-records", {
    get top() {
      return this.items.length ? this.items[0].inches : 1;
    },
    // inside x-for: `this.record`
    inches() {
      return this.record.inches.toFixed(1);
    },
    when() {
      return day(this.record.date);
    },
    bar() {
      return `width: ${Math.round((this.record.inches / this.top) * 100)}%`;
    },
  }));

  Alpine.data("reportsPanel", countyList("reports", {
    // inside x-for: `this.report`
    meta() {
      return [this.report.publisher, day(this.report.event_date)].filter(Boolean).join(" · ");
    },
  }));

  Alpine.data("sourcesPanel", () => ({
    sources: [],
    builtAt: null,
    async init() {
      try {
        const body = await getJson("sources");
        this.sources = body.sources;
        this.builtAt = body.built_at;
      } catch (error) {
        if (!isAbort(error)) console.warn("sources unavailable", error);
      }
    },
    get built() {
      return this.builtAt ? t("footer.built", { date: day(this.builtAt) }) : "";
    },
    // inside x-for: `this.source`
    retrieved() {
      return this.source.retrieved_at ? day(this.source.retrieved_at) : "";
    },
  }));
});
