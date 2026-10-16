/* Claims & rainfall by year: tiles, three column charts sharing the year axis
 * (Plotly, one y-axis each), and the year table. Hovering a year in any chart
 * shows it in all three and highlights its table row. Data: /api/v1/history. */

import { getJson, isAbort } from "./api.js";
import { t } from "./i18n.js";

const CHARTS = {
  claims: { color: "--c-claims", height: 200 },
  rain: { color: "--c-nfhl", height: 140 },
  wettest: { color: "--c-firm", height: 170, last: true }, // the one that shows the year labels
};
const ANNOTATED_YEARS = [2008, 2010, 2020]; // Dolly, Alex, Hanna: the valley's big flood years
const METRIC_FIELD = { claims: "claims", paid: "paid", rate: "claims_per_1000_policies" };

const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const dollars = (n) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n)}`);
const dash = (value, format) => (value === null || value === undefined ? "—" : format(value));
const stormName = (event) => (event || "").replace(/^(Hurricane|Tropical Storm)\s+/i, "");

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("claimsPage", () => ({
    history: null,
    metric: "claims",
    hoverYear: null,
    tables: { claims: false, rain: false, wettest: false },
    syncing: false,

    init() {
      Alpine.effect(() => this.load(Alpine.store("app").county));
      window.addEventListener("rgv:theme", () => this.draw());
    },
    async load(county) {
      try {
        this.history = await getJson("history", { county: county || null });
        this.$nextTick(() => this.draw());
      } catch (error) {
        if (!isAbort(error)) console.warn("history unavailable", error);
      }
    },

    // ---- controls
    choose(name, value) {
      this[name] = value;
      this.draw();
    },
    chosenClass(name, value) {
      return this[name] === value ? "bg-accent-soft text-ink shadow-[inset_0_0_0_1px_var(--accent-line)]" : "";
    },
    toggleTable() {
      const chart = this.$el.dataset.for;
      this.tables[chart] = !this.tables[chart];
      if (!this.tables[chart]) this.$nextTick(() => this.draw());
    },

    // ---- text
    title(chart) {
      if (chart === "claims") return t(`claims.chart.${this.metric}`);
      return t(`claims.chart.${chart}`);
    },
    unit(chart) {
      return chart === "claims" ? t("claims.unit.per_year") : t("claims.unit.inches");
    },
    get span() {
      return this.history ? t("claims.span", { first: this.history.first_year, last: this.history.last_year }) : "";
    },
    get countyName() {
      const slug = Alpine.store("app").county;
      return slug ? t("claims.county", { name: slug.charAt(0).toUpperCase() + slug.slice(1) }) : t("county.all");
    },

    // ---- tiles
    get tileClaims() {
      return this.history ? this.history.totals.claims.toLocaleString() : "";
    },
    get tileClaimsSub() {
      return this.history ? t("claims.tile.claims_sub", { first: this.history.first_year, place: this.countyName }) : "";
    },
    get tilePaid() {
      return this.history ? dollars(this.history.totals.paid) : "";
    },
    get tilePaidSub() {
      return this.history ? t("claims.tile.paid_sub", { first: this.history.first_year, last: this.history.last_year }) : "";
    },
    get tileWorst() {
      return this.history?.totals.worst_year ? String(this.history.totals.worst_year) : "—";
    },
    get tileWorstSub() {
      const totals = this.history?.totals;
      if (!totals?.worst_year) return "";
      return [totals.worst_year_event, t("claims.n_claims", { n: totals.worst_year_claims.toLocaleString() })].filter(Boolean).join(" · ");
    },
    get correlationText() {
      const c = this.history?.correlation;
      if (!c || c.with_wettest_day === null) return t("claims.correlation.none");
      return t("claims.correlation.text", { wettest: c.with_wettest_day.toFixed(2), rain: (c.with_annual_rain ?? 0).toFixed(2) });
    },
    get wettestR() {
      return dash(this.history?.correlation.with_wettest_day, (r) => r.toFixed(2));
    },
    get rainR() {
      return dash(this.history?.correlation.with_annual_rain, (r) => r.toFixed(2));
    },
    get wettestBar() {
      return `width: ${Math.max(0, (this.history?.correlation.with_wettest_day ?? 0) * 100)}%`;
    },
    get rainBar() {
      return `width: ${Math.max(0, (this.history?.correlation.with_annual_rain ?? 0) * 100)}%`;
    },

    // ---- series
    values(chart) {
      const years = this.history?.years || [];
      if (chart === "rain") return years.map((y) => y.rain_inches);
      if (chart === "wettest") return years.map((y) => y.wettest_day_inches);
      return years.map((y) => y[METRIC_FIELD[this.metric]]);
    },
    format(chart, value) {
      if (value === null || value === undefined) return "—";
      if (chart !== "claims") return value.toFixed(1);
      if (this.metric === "paid") return dollars(value);
      if (this.metric === "rate") return value.toFixed(1);
      return value.toLocaleString();
    },
    tableRows(chart) {
      const years = this.history?.years || [];
      const values = this.values(chart);
      return years.map((y, i) => ({ year: y.year, value: this.format(chart, values[i]) })).reverse();
    },
    get rows() {
      return (this.history?.years || []).map((y) => ({
        year: y.year,
        claims: y.claims.toLocaleString(),
        paid: dollars(y.paid),
        rate: dash(y.claims_per_1000_policies, (v) => v.toFixed(1)),
        rain: dash(y.rain_inches, (v) => v.toFixed(1)),
        wettest: dash(y.wettest_day_inches, (v) => v.toFixed(2)),
        event: y.flood_event || "",
      })).reverse();
    },
    get tableNote() {
      return `${this.countyName} · ${t("claims.table.hint")}`;
    },
    // inside x-for: `this.row`
    rowClass() {
      return this.hoverYear === this.row.year ? "is-selected" : "";
    },

    // ---- charts
    figure(chart) {
      const years = (this.history?.years || []).map((y) => y.year);
      const values = this.values(chart);
      const color = token(CHARTS[chart].color);
      const ink = token("--text");
      const muted = token("--muted");
      const annotations = chart !== "claims" ? [] : ANNOTATED_YEARS.flatMap((year) => {
        const row = this.history.years.find((y) => y.year === year);
        const i = years.indexOf(year);
        if (!row || !values[i]) return [];
        return [{ x: year, y: values[i], text: `${year} ${stormName(row.flood_event)}`.trim(), showarrow: false,
          yanchor: "bottom", yshift: 4, font: { size: 11, color: ink, family: "Public Sans" } }];
      });
      const last = (this.history?.years || []).at(-1)?.year ?? 2025;
      return {
        data: [{
          type: "bar", x: years, y: values, marker: { color, line: { width: 0 } },
          customdata: values.map((v) => this.format(chart, v)),
          hovertemplate: "%{x} · %{customdata}<extra></extra>",
        }],
        layout: {
          height: CHARTS[chart].height,
          margin: { l: 56, r: 16, t: 14, b: CHARTS[chart].last ? 26 : 6 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          bargap: 0.3,
          hovermode: "x",
          hoverlabel: { bgcolor: token("--panel2"), bordercolor: token("--accent"), font: { color: ink, family: "Public Sans", size: 11 } },
          font: { family: "Public Sans", size: 10, color: muted },
          xaxis: {
            range: [1977.4, last + 0.6], fixedrange: true, showgrid: false, zeroline: false, ticks: "",
            showticklabels: Boolean(CHARTS[chart].last), dtick: 5, tick0: 1980,
            showspikes: true, spikemode: "across", spikethickness: 1, spikecolor: token("--accent"), spikedash: "solid",
          },
          yaxis: { fixedrange: true, gridcolor: token("--line"), zeroline: false, nticks: 3, rangemode: "tozero",
                   tickformat: chart === "claims" && this.metric === "paid" ? "$.2s" : "~s" },
          annotations,
        },
      };
    },
    draw() {
      if (!this.history || !window.Plotly) return;
      for (const chart of Object.keys(CHARTS)) {
        const element = this.$root.querySelector(`[data-chart="${chart}"]`);
        if (!element || this.tables[chart]) continue;
        const { data, layout } = this.figure(chart);
        window.Plotly.react(element, data, layout, { displayModeBar: false, responsive: true });
        if (!element.dataset.wired) this.wire(element);
      }
    },
    /** One hover, three charts: show the same year everywhere and in the table. */
    wire(element) {
      element.dataset.wired = "true";
      element.on("plotly_hover", (event) => {
        const point = event.points[0];
        this.hoverYear = point.x;
        if (this.syncing) return;
        this.syncing = true;
        for (const other of this.$root.querySelectorAll("[data-chart]")) {
          if (other !== element && other.data) window.Plotly.Fx.hover(other, [{ curveNumber: 0, pointNumber: point.pointNumber }]);
        }
        this.syncing = false;
      });
      element.on("plotly_unhover", () => {
        if (this.syncing) return;
        this.hoverYear = null;
        for (const other of this.$root.querySelectorAll("[data-chart]")) if (other !== element && other.data) window.Plotly.Fx.unhover(other);
      });
    },
  }));
});
