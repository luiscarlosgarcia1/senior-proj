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
    alertCount: 0,
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

  Alpine.data("countySelect", () => ({
    get county() {
      return Alpine.store("app").county;
    },
    choose(event) {
      Alpine.store("app").setCounty(event.target.value);
    },
  }));

  Alpine.data("alertPill", () => ({
    get label() {
      return t("alerts.pill", { n: Alpine.store("app").alertCount });
    },
    async init() {
      const refresh = async () => {
        try {
          Alpine.store("app").alertCount = (await getJson("live-signals")).signals.length;
        } catch (error) {
          if (!isAbort(error)) console.warn("live alerts unavailable", error);
        }
      };
      await refresh();
      setInterval(refresh, 60_000);
    },
  }));
});
