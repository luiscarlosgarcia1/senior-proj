/* Shared page state (Alpine stores) and the header's small components.
 * Loaded on every page before Alpine itself, so its registrations are in
 * place when Alpine starts. Other modules import { app } to read and change it. */

import { getJson, isAbort } from "./api.js";
import { t } from "./i18n.js";

const THEME_KEY = "rgv-theme";

/** Fire `rgv:<name>` on window so modules outside Alpine (map, charts) can follow. */
export const emit = (name, detail) => window.dispatchEvent(new CustomEvent(`rgv:${name}`, { detail }));

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.store("app", {
    county: "",
    theme: document.documentElement.dataset.theme || "dark",
    loading: false,
    view: "map", // phones show one view at a time: map, layers or events
    setCounty(slug) {
      if (slug === this.county) return;
      this.county = slug;
      emit("county", slug);
    },
    setTheme(theme) {
      this.theme = theme;
      document.documentElement.dataset.theme = theme;
      try {
        localStorage.setItem(THEME_KEY, theme);
      } catch {
        /* private mode: the choice lasts for this page only */
      }
      emit("theme", theme);
    },
  });

  Alpine.data("themeToggle", () => ({
    get light() {
      return Alpine.store("app").theme === "light";
    },
    toggle(event) {
      Alpine.store("app").setTheme(event.target.checked ? "light" : "dark");
    },
  }));

  Alpine.data("bottomNav", () => ({
    // the buttons carry data-view; `this.$el` is the button being evaluated
    show() {
      Alpine.store("app").view = this.$el.dataset.view;
      if (this.$el.dataset.view === "map") emit("map-shown");
    },
    pressed() {
      return Alpine.store("app").view === this.$el.dataset.view;
    },
    classFor() {
      return this.pressed() ? "text-ink nav-active" : "text-muted";
    },
  }));

  Alpine.data("countySelect", () => ({
    get county() {
      return Alpine.store("app").county;
    },
    choose(event) {
      Alpine.store("app").setCounty(event.target.value);
    },
  }));

  // Live official alerts, polled once a minute for the whole page: the header
  // pill counts them and the map page's alerts panel lists them.
  Alpine.store("alerts", {
    signals: [],
    refreshedAt: null,
    loaded: false,
    started: false,
    async refresh() {
      try {
        const body = await getJson("live-signals");
        this.signals = body.signals;
        this.refreshedAt = body.refreshed_at;
      } catch (error) {
        if (!isAbort(error)) console.warn("live alerts unavailable", error);
      } finally {
        this.loaded = true;
      }
    },
    start() {
      if (this.started) return;
      this.started = true;
      this.refresh();
      setInterval(() => this.refresh(), 60_000);
    },
  });

  Alpine.data("alertPill", () => ({
    get label() {
      return t("alerts.pill", { n: Alpine.store("alerts").signals.length });
    },
    init() {
      Alpine.store("alerts").start();
    },
  }));
});
