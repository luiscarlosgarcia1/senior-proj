/* Trends over time: rain by year and by month, NOAA flood events, NWS flood
 * reports and news stories, as bar charts on one year axis (Plotly), each with
 * a "view table" toggle. Pick a county and, optionally, one rain gauge.
 * Data: /api/v1/trends. */

import { getJson, isAbort } from "./api.js";
import { t } from "./i18n.js";

const FIRST_YEAR = 1978; // the rain record's first year; every chart shares this axis
const CHARTS = {
  rain: { color: "--c-nfhl", height: 150 },
  wettest: { color: "--c-firm", height: 130 },
  over2: { color: "--c-claims", height: 130 },
  months: { color: "--c-nfhl", height: 150 },
  events: { stack: true, height: 170 },
  nws: { stack: true, height: 150 },
  news: { color: "--c-photos", height: 130 },
};
// Stacked series take these in turn.
const PALETTE = ["--c-claims", "--c-nfhl", "--c-firm", "--c-photos", "--c-infra", "--c-drain", "--c-nws"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const sum = (numbers) => numbers.reduce((total, n) => total + n, 0);
const kindName = (key) => key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("trendsPage", () => {
    let loadedCounty = null; // the county the gauge choice belongs to (not reactive on purpose)

    return {
      trends: null,
      station: "",
      tables: { rain: false, wettest: false, over2: false, months: false, events: false, nws: false, news: false },

      init() {
        Alpine.effect(() => this.load(Alpine.store("app").county));
        window.addEventListener("rgv:theme", () => this.draw());
      },
      async load(county) {
        if (county !== loadedCounty) {
          loadedCounty = county;
          this.station = ""; // a gauge belongs to one county
        }
        try {
          this.trends = await getJson("trends", { county: county || null, station: this.station || null });
          this.$nextTick(() => this.draw());
        } catch (error) {
          if (isAbort(error)) return;
          if (error.status === 404 && this.station) {
            this.station = "";
            return this.load(county);
          }
          console.warn("trends unavailable", error);
        }
      },
      chooseStation(event) {
        this.station = event.target.value;
        this.load(loadedCounty);
      },
      toggleTable() {
        const chart = this.$el.dataset.for;
        this.tables[chart] = !this.tables[chart];
        if (!this.tables[chart]) this.$nextTick(() => this.draw());
      },

      // ---- the gauge menu (inside x-for: `this.s`)
      get stations() {
        return this.trends?.stations || [];
      },
      isChosen() {
        return this.s.station_id === this.station;
      },

      // ---- text
      get first() {
        return FIRST_YEAR;
      },
      get last() {
        return this.trends?.events_by_year.at(-1)?.year ?? new Date().getUTCFullYear() - 1;
      },
      get place() {
        const slug = Alpine.store("app").county;
        const gauge = this.stations.find((s) => s.station_id === this.station);
        if (gauge) return gauge.name;
        return slug ? t("claims.county", { name: slug.charAt(0).toUpperCase() + slug.slice(1) }) : t("county.all");
      },
      get span() {
        return this.trends ? t("trends.span", { place: this.place, first: this.first, last: this.last }) : "";
      },
      get noRain() {
        return Boolean(this.trends) && this.trends.rain_years.length === 0;
      },

      // ---- tiles
      get wettestYear() {
        const complete = (this.trends?.rain_years || []).filter((y) => y.complete && y.inches !== null);
        return complete.length ? complete.reduce((best, y) => (y.inches > best.inches ? y : best)) : null;
      },
      get tileWettest() {
        return this.wettestYear ? String(this.wettestYear.year) : "—";
      },
      get tileWettestSub() {
        return this.wettestYear ? t("trends.tile.wettest_sub", { inches: this.wettestYear.inches.toFixed(1) }) : "";
      },
      get tileEvents() {
        return this.trends ? sum(this.trends.events_by_year.map((y) => y.total)).toLocaleString() : "";
      },
      get tileEventsSub() {
        return this.trends ? t("trends.tile.events_sub", { first: this.trends.events_by_year[0].year, last: this.last }) : "";
      },
      get tileNws() {
        return this.trends ? sum(this.trends.nws_by_year.map((y) => y.total)).toLocaleString() : "";
      },
      get tileNwsSub() {
        return this.trends ? t("trends.tile.nws_sub", { first: this.trends.nws_by_year[0].year, last: this.last }) : "";
      },
      get tileNews() {
        return this.trends ? sum(this.trends.news_by_year.map((y) => y.count)).toLocaleString() : "";
      },
      get tileNewsSub() {
        return this.trends?.news_first_year ? t("trends.tile.news_sub", { first: this.trends.news_first_year, last: this.last }) : "";
      },

      // ---- series: each chart is a list of traces {name, x, y, text}
      traces(chart) {
        const trends = this.trends;
        if (!trends) return [];
        const years = (rows) => rows.map((row) => row.year);
        if (chart === "rain" || chart === "wettest" || chart === "over2") {
          const field = { rain: "inches", wettest: "wettest_day_inches", over2: "days_over_2_inches" }[chart];
          return [{
            name: t(`trends.chart.${chart}`), x: years(trends.rain_years), y: trends.rain_years.map((y) => y[field]),
            text: trends.rain_years.map((y) => String(y.year)),
            opacity: trends.rain_years.map((y) => (y.complete ? 1 : 0.35)), // a gauge year with days missing is drawn pale
          }];
        }
        if (chart === "months") {
          const rows = trends.rain_months;
          return [{
            name: t("trends.chart.months"), x: rows.map((m) => m.year + (m.month - 0.5) / 12), y: rows.map((m) => m.inches),
            text: rows.map((m) => `${MONTHS[m.month - 1]} ${m.year}`),
          }];
        }
        if (chart === "news") {
          return [{
            name: t("trends.chart.news"), x: years(trends.news_by_year), y: trends.news_by_year.map((y) => y.count),
            text: trends.news_by_year.map((y) => String(y.year)),
          }];
        }
        const [rows, group] = chart === "events" ? [trends.events_by_year, "by_type"] : [trends.nws_by_year, "by_kind"];
        const names = [...new Set(rows.flatMap((row) => Object.keys(row[group])))].sort();
        return names.map((name) => ({
          name: chart === "nws" ? kindName(name) : name, x: years(rows), y: rows.map((row) => row[group][name] ?? 0),
          text: rows.map((row) => String(row.year)),
        }));
      },
      tableRows(chart) {
        const traces = this.traces(chart);
        const rows = [];
        const longest = traces.reduce((best, trace) => (trace.x.length > best.length ? trace.x : best), []);
        longest.forEach((x, i) => {
          const parts = traces.map((trace) => [trace.name, trace.y[i]]).filter(([, value]) => value !== null && value !== undefined);
          const stacked = CHARTS[chart].stack;
          const value = stacked
            ? `${sum(parts.map(([, v]) => v))}${parts.length > 1 ? ` (${parts.filter(([, v]) => v).map(([n, v]) => `${n} ${v}`).join(", ")})` : ""}`
            : parts.length ? String(parts[0][1]) : "—";
          rows.push({ key: String(x), label: traces[0].text[i], value });
        });
        return rows.reverse();
      },

      // ---- charts
      figure(chart) {
        const settings = CHARTS[chart];
        const ink = token("--text");
        const muted = token("--muted");
        const data = this.traces(chart).map((trace, i) => ({
          type: "bar", name: trace.name, x: trace.x, y: trace.y, customdata: trace.text,
          marker: { color: token(settings.color || PALETTE[i % PALETTE.length]), line: { width: 0 }, opacity: trace.opacity ?? 1 },
          hovertemplate: `%{customdata} · %{y}<extra>${settings.stack ? trace.name : ""}</extra>`,
        }));
        return {
          data,
          layout: {
            height: settings.height,
            margin: { l: 56, r: 16, t: 10, b: 24 },
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            bargap: chart === "months" ? 0 : 0.3,
            barmode: settings.stack ? "stack" : "group",
            hovermode: "closest",
            showlegend: Boolean(settings.stack),
            legend: { orientation: "h", y: 1.18, x: 0, font: { size: 10, color: muted } },
            hoverlabel: { bgcolor: token("--panel2"), bordercolor: token("--accent"), font: { color: ink, family: "Public Sans", size: 11 } },
            font: { family: "Public Sans", size: 10, color: muted },
            xaxis: { range: [this.first - 0.6, this.last + 0.6], fixedrange: true, showgrid: false, zeroline: false, dtick: 5, tick0: 1980 },
            yaxis: { fixedrange: true, gridcolor: token("--line"), zeroline: false, nticks: 3, rangemode: "tozero", tickformat: "~s" },
          },
        };
      },
      draw() {
        if (!this.trends || !window.Plotly) return;
        for (const chart of Object.keys(CHARTS)) {
          const element = this.$root.querySelector(`[data-chart="${chart}"]`);
          if (!element || this.tables[chart]) continue;
          const { data, layout } = this.figure(chart);
          window.Plotly.react(element, data, layout, { displayModeBar: false, responsive: true });
        }
      },
    };
  });
});
