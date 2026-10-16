/* Address search, through the app's own /api/v1/geocode (which keeps to the
 * geocoder's usage policy). `/` focuses the box; Enter takes the first result;
 * picking a result flies the map there and drops a marker. */

import { getJson, isAbort } from "../api.js";
import { t } from "../i18n.js";
import { mapReady, maplibregl } from "../map/main.js";

const DEBOUNCE_MS = 300;
const MIN_LENGTH = 3;
let marker = null;

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("searchBox", () => ({
    q: "",
    results: [],
    message: "",
    open: false,
    timer: null,
    init() {
      window.addEventListener("keydown", (event) => {
        const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
        if (event.key === "/" && !typing && this.$el.offsetParent !== null) {
          event.preventDefault();
          this.$refs.input.focus();
        }
      });
    },
    typed(event) {
      this.q = event.target.value;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.search(), DEBOUNCE_MS);
    },
    async search() {
      const q = this.q.trim();
      if (q.length < MIN_LENGTH) {
        Object.assign(this, { results: [], message: "", open: false });
        return;
      }
      try {
        this.results = await getJson("geocode", { q });
        this.message = this.results.length ? "" : t("search.none");
      } catch (error) {
        if (isAbort(error)) return;
        this.results = [];
        this.message = t("search.unavailable");
      }
      this.open = true;
    },
    pickFirst() {
      if (this.results.length) this.go(this.results[0]);
    },
    // inside x-for: `this.place`
    pick() {
      this.go(this.place);
    },
    async go(place) {
      this.q = place.label;
      this.open = false;
      Alpine.store("app").view = "map";
      const map = await mapReady;
      marker?.remove();
      marker = new maplibregl.Marker({ color: getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() })
        .setLngLat([place.lon, place.lat])
        .addTo(map);
      map.flyTo({ center: [place.lon, place.lat], zoom: 15, duration: 900 });
    },
    close() {
      this.open = false;
    },
  }));
});
