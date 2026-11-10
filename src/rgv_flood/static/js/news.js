/* What the news archive says, measured against the data: weather stories per month beside rain, NWS flood
 * reports and flood-insurance claims; the months where they disagree; the busiest news days, each opening a
 * day-by-day timeline of every outlet's stories; the streets and waterways named again and again; water-service
 * problems town by town; and each county's coverage against its claims and reports.
 * Data: /api/v1/news/insights and /api/v1/news/timeline. */

import { getJson, isAbort } from "./api.js";
import { t } from "./i18n.js";
import { day } from "./panels/format.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TIMELINE_DAYS_AROUND = 3;

const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const sum = (numbers) => numbers.reduce((total, n) => total + n, 0);
const monthName = (key) => `${MONTHS[Number(key.slice(5, 7)) - 1]} ${key.slice(0, 4)}`;
const capitalized = (slug) => slug.charAt(0).toUpperCase() + slug.slice(1);

/** "2020-07-27" moved by `days`, as an ISO day. */
function shift(iso, days) {
  const moment = new Date(`${iso}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

/** A rank correlation in words: the number and how strong it is. */
function strength(r) {
  if (r === null || r === undefined) return "—";
  const word = Math.abs(r) >= 0.5 ? "strong" : Math.abs(r) >= 0.3 ? "moderate" : Math.abs(r) >= 0.1 ? "weak" : "none";
  return `${r.toFixed(2)} · ${t(`news.page.r.${word}`)}`;
}

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("newsPage", () => ({
    insights: null,
    timeline: [],
    openDate: null,
    loadingTimeline: false,

    init() {
      Alpine.effect(() => this.load(Alpine.store("app").county));
      window.addEventListener("rgv:theme", () => this.draw());
    },
    async load(county) {
      try {
        this.insights = await getJson("news/insights", { county: county || null });
        this.timeline = [];
        this.openDate = null;
        this.$nextTick(() => this.draw());
      } catch (error) {
        if (!isAbort(error)) console.warn("news insights unavailable", error);
      }
    },

    // ---- header and tiles
    get months() {
      return this.insights?.months || [];
    },
    get place() {
      const slug = Alpine.store("app").county;
      return slug ? t("claims.county", { name: capitalized(slug) }) : t("county.all");
    },
    get span() {
      if (!this.months.length) return "";
      return t("news.page.span", { place: this.place, first: monthName(this.months[0].month), last: monthName(this.months.at(-1).month) });
    },
    get tileStories() {
      return this.months.length ? sum(this.months.map((m) => m.stories)).toLocaleString() : "—";
    },
    get tileStoriesSub() {
      return t(Alpine.store("app").county ? "news.page.tile.stories_sub_county" : "news.page.tile.stories_sub");
    },
    get tileRain() {
      return strength(this.insights?.correlation?.rain);
    },
    get tileRainSub() {
      const c = this.insights?.correlation;
      return c ? t("news.page.tile.rain_sub", { months: c.rain_months, next: strength(c.rain_next_month) }) : "";
    },
    get tileNws() {
      return strength(this.insights?.correlation?.nws);
    },
    get tileNwsSub() {
      return t("news.page.tile.nws_sub");
    },
    get tileClaims() {
      return strength(this.insights?.correlation?.claims);
    },
    get tileClaimsSub() {
      return t("news.page.tile.claims_sub");
    },

    // ---- months where the news and the rain disagree (inside x-for: `this.m`)
    get wetQuiet() {
      return this.insights?.wet_quiet || [];
    },
    get loudDry() {
      return this.insights?.loud_dry || [];
    },
    monthName() {
      return monthName(this.m.month);
    },
    monthNumbers() {
      return t("news.page.month_numbers", { rain: this.m.rain_inches.toFixed(1), stories: this.m.stories });
    },

    // ---- the busiest days (inside x-for: `this.d`) and the timeline around one
    get busiest() {
      return this.insights?.busiest_days || [];
    },
    dayName() {
      return day(this.d.date);
    },
    dayCounts() {
      return t("news.page.day_counts", { stories: this.d.stories, outlets: this.d.outlets });
    },
    isOpen() {
      return this.openDate === this.d.date;
    },
    dayClass() {
      return this.isOpen() ? "border-accent" : "";
    },
    async openDay() {
      const date = this.d.date;
      this.openDate = date;
      this.loadingTimeline = true;
      try {
        this.timeline = await getJson("news/timeline", {
          start: shift(date, -TIMELINE_DAYS_AROUND), end: shift(date, TIMELINE_DAYS_AROUND), county: Alpine.store("app").county || null,
        });
      } catch (error) {
        if (!isAbort(error)) console.warn("news timeline unavailable", error);
      } finally {
        this.loadingTimeline = false;
      }
    },
    get timelineTitle() {
      return this.openDate ? t("news.page.timeline_title", { day: day(this.openDate), around: TIMELINE_DAYS_AROUND }) : "";
    },
    timelineDay() {
      return day(this.tday.date);
    },
    // inside x-for: `this.story` (components/news_story.html)
    storyMeta() {
      return [this.story.publisher, day(this.story.published_at), this.story.city].filter(Boolean).join(" · ");
    },
    fromAddress() {
      return this.story.headline_from === "address";
    },
    hasOthers() {
      return this.story.also_reported_by.length > 0;
    },

    // ---- recurring places (this.p) and water-service problems (this.w)
    get places() {
      return this.insights?.places || [];
    },
    placeSpan() {
      return t("news.page.span_days", { first: day(this.p.first), last: day(this.p.last) });
    },
    get towns() {
      return this.insights?.water_systems || [];
    },
    townSpan() {
      return t("news.page.span_days", { first: day(this.w.first), last: day(this.w.last) });
    },

    // ---- coverage by county (this.c)
    get coverage() {
      return this.insights?.coverage || [];
    },
    countyName() {
      return capitalized(this.c.county);
    },
    perClaims() {
      return this.c.stories_per_100_claims ?? "—";
    },
    perReport() {
      return this.c.stories_per_nws_report ?? "—";
    },
    get languageText() {
      const languages = this.insights?.languages;
      if (!languages) return "";
      const total = languages.spanish + languages.english;
      const share = total ? Math.round((100 * languages.spanish) / total) : 0;
      return t("news.page.languages", { spanish: languages.spanish.toLocaleString(), total: total.toLocaleString(), share });
    },

    // ---- charts
    figure(chart) {
      const months = this.months;
      const x = months.map((m) => `${m.month}-15`);
      const text = months.map((m) => monthName(m.month));
      const ink = token("--text");
      const muted = token("--muted");
      const series = chart === "stories"
        ? [
            { type: "bar", name: t("news.page.series.stories"), y: months.map((m) => m.stories), color: "--c-photos" },
            { type: "scatter", name: t("news.page.series.rain"), y: months.map((m) => m.rain_inches), color: "--c-nfhl", yaxis: "y2" },
          ]
        : [
            { type: "bar", name: t("news.page.series.nws"), y: months.map((m) => m.nws_reports), color: "--c-nws" },
            { type: "scatter", name: t("news.page.series.claims"), y: months.map((m) => m.claims), color: "--c-claims", yaxis: "y2" },
          ];
      const data = series.map((s) => ({
        type: s.type, name: s.name, x, y: s.y, customdata: text, yaxis: s.yaxis || "y",
        mode: s.type === "scatter" ? "lines" : undefined,
        connectgaps: false,
        marker: { color: token(s.color), line: { width: 0 } },
        line: { color: token(s.color), width: 1.5 },
        hovertemplate: `%{customdata} · %{y}<extra>${s.name}</extra>`,
      }));
      const axis = { fixedrange: true, gridcolor: token("--line"), zeroline: false, nticks: 3, rangemode: "tozero", tickformat: "~s" };
      return {
        data,
        layout: {
          height: 190,
          margin: { l: 48, r: 48, t: 10, b: 24 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          bargap: 0.15,
          hovermode: "x unified",
          showlegend: true,
          legend: { orientation: "h", y: 1.2, x: 0, font: { size: 10, color: muted } },
          hoverlabel: { bgcolor: token("--panel2"), bordercolor: token("--accent"), font: { color: ink, family: "Public Sans", size: 11 } },
          font: { family: "Public Sans", size: 10, color: muted },
          xaxis: { type: "date", fixedrange: true, showgrid: false, zeroline: false },
          yaxis: axis,
          // "auto": Plotly otherwise lines the right axis's ticks up with the left's, at odd numbers
          yaxis2: { ...axis, overlaying: "y", side: "right", showgrid: false, tickmode: "auto" },
        },
      };
    },
    draw() {
      if (!this.months.length || !window.Plotly) return;
      for (const chart of ["stories", "signals"]) {
        const element = this.$root.querySelector(`[data-chart="${chart}"]`);
        if (!element) continue;
        const { data, layout } = this.figure(chart);
        window.Plotly.react(element, data, layout, { displayModeBar: false, responsive: true });
      }
    },
  }));
});
