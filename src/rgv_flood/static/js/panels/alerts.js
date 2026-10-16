/* Live official alerts (NWS warnings, TxDOT closures, county notices), pinned
 * at the top of the side panel. The list comes from the shared alerts store,
 * narrowed to the selected county. */

import { t } from "../i18n.js";
import { ago, alertSeverity } from "./format.js";

const SOURCE_BADGES = { nws: "NWS", drivetexas: "TxDOT", "hidalgo-rss": "County" };

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("alertsPanel", () => ({
    init() {
      Alpine.store("alerts").start();
    },
    get signals() {
      const county = Alpine.store("app").county;
      return Alpine.store("alerts").signals.filter((signal) => !county || signal.county_slugs.includes(county));
    },
    get updated() {
      const at = Alpine.store("alerts").refreshedAt;
      return at ? t("alerts.updated", { when: ago(at) }) : t("alerts.never");
    },
    get empty() {
      return Alpine.store("alerts").loaded && this.signals.length === 0;
    },
    // inside x-for: `this.signal`
    badge() {
      const source = this.signal.source.toLowerCase();
      const key = Object.keys(SOURCE_BADGES).find((prefix) => source.includes(prefix));
      return key ? SOURCE_BADGES[key] : this.signal.source_publisher;
    },
    stripe() {
      return `background: var(--sev-${alertSeverity(this.signal.summary)})`;
    },
    meta() {
      const until = this.signal.expires_at ? t("alerts.until", { when: new Date(this.signal.expires_at).toLocaleString("en-US", { timeZone: "America/Chicago", dateStyle: "medium", timeStyle: "short" }) }) : "";
      return [this.signal.source_publisher, until].filter(Boolean).join(" · ");
    },
  }));
});
