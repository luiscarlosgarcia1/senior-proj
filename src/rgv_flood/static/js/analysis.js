/* Claims and rainfall, year by year.
 *
 * Three column charts share one row of years. Each shows one measure on its
 * own axis (two scales on one chart would invite false comparisons), and a
 * crosshair follows the pointer across all three so a year reads straight
 * down. The table below holds every value, so nothing depends on hovering.
 */

const histories = JSON.parse(document.getElementById("history-data").textContent);
const form = document.getElementById("analysis-filters");
const tooltip = document.getElementById("viz-tooltip");

// Validated as a set (dataviz palette check, all pairs, on the white card).
const COLORS = { claims: "#eb6834", rain: "#2a78d6", wettest: "#4a3aa7" };
const INK = { muted: "#898781", grid: "#e1e0d9", baseline: "#c3c2b7", missing: "#d4d2ca" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Chart geometry, in viewBox units (the SVG scales to its card).
const W = 960;
const H = 200;
const M = { top: 22, right: 12, bottom: 26, left: 58 };
const SVG = "http://www.w3.org/2000/svg";

// ---- formatting -----------------------------------------------------------------

const count = (n) => Math.round(n).toLocaleString();
function dollars(n) {
  const [divisor, suffix] = n >= 1e9 ? [1e9, "B"] : n >= 1e6 ? [1e6, "M"] : n >= 1e3 ? [1e3, "K"] : [1, ""];
  const scaled = n / divisor;
  return `$${scaled >= 10 || divisor === 1 ? Math.round(scaled) : scaled.toFixed(1)}${suffix}`;
}
const inches = (n, digits = 1) => n.toFixed(digits);

/** What FEMA called the year's flood, or failing that the month most claims came in. */
function floodName(y) {
  if (y.flood_event) return y.flood_event;
  return y.busiest_month ? `${MONTHS[y.busiest_month - 1]} ${y.year}` : "";
}

// ---- what the top chart can show ----------------------------------------------

const METRICS = {
  claims: {
    title: "Flood-insurance claims per year",
    note: "Counted in the year of the loss.",
    value: (y) => y.claims,
    axis: count,
  },
  paid: {
    title: "Dollars paid on those claims",
    note: "As paid, not adjusted for inflation; building, contents and code-upgrade payments together.",
    value: (y) => y.paid,
    axis: dollars,
  },
  rate: {
    title: "Claims per 1,000 insured policies",
    note: "From 2009, when FEMA's policy counts begin. A rate shows how hard a flood hit the homes that were insured, whatever their number.",
    value: (y) => y.claims_per_1000_policies,
    axis: (n) => (n >= 10 ? Math.round(n) : n.toFixed(1)),
  },
};

// ---- SVG helpers ------------------------------------------------------------------

function svgEl(name, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent?.appendChild(node);
  return node;
}

/** Round, readable axis steps (1, 2, 2.5 or 5 times a power of ten). */
function niceTicks(max, target = 4) {
  if (!(max > 0)) return [0, 1];
  const rough = max / target;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
  const ticks = [];
  for (let t = 0; t < max + step * 0.999; t += step) ticks.push(Number(t.toFixed(10)));
  return ticks;
}

/** A column from the baseline up to `top`, with a 4px rounded data end. */
function columnPath(x, width, top, baseline) {
  const r = Math.min(4, width / 2, baseline - top);
  return (
    `M${x},${baseline} V${top + r} Q${x},${top} ${x + r},${top} ` +
    `H${x + width - r} Q${x + width},${top} ${x + width},${top + r} V${baseline} Z`
  );
}

/**
 * Draw one column chart into `container`. Returns `show(i)` / `hide()` to move
 * the year highlight, and calls `onHover(i, event)` / `onLeave()` from its hit areas.
 */
function columnChart(container, years, { value, color, format, labels = [], describe, onHover, onLeave }) {
  container.replaceChildren();
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const baseline = M.top + plotH;
  const band = plotW / years.length;
  const barW = Math.min(24, band - 2); // a 2px gap between neighbours
  const values = years.map(value);
  const ticks = niceTicks(Math.max(0, ...values.filter((v) => v != null)));
  const top = ticks.at(-1);
  const yOf = (v) => baseline - (v / top) * plotH;
  const xOf = (i) => M.left + i * band + (band - barW) / 2;

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": describe(values) }, container);

  // Recessive grid and axis.
  for (const t of ticks) {
    svgEl("line", { x1: M.left, x2: W - M.right, y1: yOf(t), y2: yOf(t), stroke: t ? INK.grid : INK.baseline, "stroke-width": 1 }, svg);
    svgEl("text", { x: M.left - 8, y: yOf(t) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = format(t);
  }
  years.forEach((y, i) => {
    if (y.year % 5 === 0 || i === 0 || i === years.length - 1) {
      svgEl("text", { x: xOf(i) + barW / 2, y: H - 8, "text-anchor": "middle", class: "tick" }, svg).textContent = y.year;
    }
  });

  // The year highlight sits behind the columns.
  const highlight = svgEl("rect", { y: M.top, width: band, height: plotH, class: "year-highlight", visibility: "hidden" }, svg);

  values.forEach((v, i) => {
    if (v == null) {
      // No data for this year: a flat grey tick, so a gap isn't mistaken for zero.
      svgEl("rect", { x: xOf(i), y: baseline - 2, width: barW, height: 2, fill: INK.missing }, svg);
    } else if (v > 0) {
      svgEl("path", { d: columnPath(xOf(i), barW, Math.min(yOf(v), baseline - 1), baseline), fill: color }, svg);
    }
  });

  // Direct labels on the few years the story is about.
  for (const { index, text } of labels) {
    const v = values[index];
    const x = Math.min(Math.max(xOf(index) + barW / 2, M.left + 40), W - M.right - 40);
    svgEl("text", { x, y: Math.max(yOf(v) - 6, 11), "text-anchor": "middle", class: "bar-label" }, svg).textContent = text;
  }

  // Hit areas: a whole year's band, taller and wider than the column.
  years.forEach((_y, i) => {
    const hit = svgEl("rect", { x: M.left + i * band, y: M.top, width: band, height: plotH, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (event) => onHover(i, event));
  });
  svg.addEventListener("pointerleave", onLeave);

  return {
    show(i) {
      highlight.setAttribute("x", M.left + i * band);
      highlight.setAttribute("visibility", "visible");
    },
    hide() {
      highlight.setAttribute("visibility", "hidden");
    },
  };
}

/** The biggest years, at least four years apart so their labels don't collide. */
function standoutYears(years, value, howMany = 4) {
  const ranked = years.map((y, index) => ({ index, v: value(y) ?? 0 })).filter((r) => r.v > 0).sort((a, b) => b.v - a.v);
  const chosen = [];
  for (const r of ranked) {
    if (chosen.length === howMany) break;
    if (chosen.every((c) => Math.abs(c.index - r.index) >= 4)) chosen.push(r);
  }
  return chosen;
}

// ---- tooltip ------------------------------------------------------------------------

function tooltipRow(parent, value, label, color) {
  const row = document.createElement("div");
  row.className = "tip-row";
  if (color) {
    const key = document.createElement("span");
    key.className = "tip-key";
    key.style.background = color;
    row.append(key);
  }
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = ` ${label}`;
  row.append(strong, span);
  parent.append(row);
}

function showTooltip(y, event) {
  tooltip.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "tip-year";
  heading.textContent = floodName(y) ? `${y.year} · ${floodName(y)}` : String(y.year);
  tooltip.append(heading);
  tooltipRow(tooltip, count(y.claims), y.claims === 1 ? "claim" : "claims", COLORS.claims);
  tooltipRow(tooltip, dollars(y.paid), "paid");
  if (y.claims_per_1000_policies != null) tooltipRow(tooltip, y.claims_per_1000_policies.toFixed(1), "claims per 1,000 policies");
  if (y.rain_inches != null) tooltipRow(tooltip, `${inches(y.rain_inches)} in`, "of rain over the year", COLORS.rain);
  else tooltipRow(tooltip, "—", "no gauge kept a full year", COLORS.rain);
  if (y.wettest_day_inches != null) tooltipRow(tooltip, `${inches(y.wettest_day_inches, 2)} in`, "on the wettest day", COLORS.wettest);
  if (y.noaa_flood_events != null) tooltipRow(tooltip, count(y.noaa_flood_events), "NOAA flood events");
  if (y.nws_flood_reports != null) tooltipRow(tooltip, count(y.nws_flood_reports), "flood reports to the NWS");

  tooltip.hidden = false;
  const pad = 14;
  const { width, height } = tooltip.getBoundingClientRect();
  const left = event.clientX + pad + width > window.innerWidth ? event.clientX - pad - width : event.clientX + pad;
  const topPos = Math.min(event.clientY + pad, window.innerHeight - height - 8);
  tooltip.style.left = `${Math.max(8, left)}px`;
  tooltip.style.top = `${Math.max(8, topPos)}px`;
}

// ---- the page ----------------------------------------------------------------------

function statTile(parent, label, value, detail) {
  const tile = document.createElement("div");
  tile.className = "stat-tile";
  for (const [className, text] of [["stat-label", label], ["stat-value", value], ["stat-detail", detail]]) {
    if (!text) continue;
    const node = document.createElement("div");
    node.className = className;
    node.textContent = text;
    tile.append(node);
  }
  parent.append(tile);
}

function renderStats(history, years) {
  const row = document.getElementById("stat-row");
  row.replaceChildren();
  const { totals, correlation } = history;
  const span = `${years[0].year}–${years.at(-1).year}`;
  statTile(row, `Claims, ${span}`, count(totals.claims), `${dollars(totals.paid)} paid`);
  if (totals.worst_year) {
    const worst = years.find((y) => y.year === totals.worst_year);
    statTile(row, "Most claims in one year", String(totals.worst_year), `${count(totals.worst_year_claims)} claims · ${floodName(worst)}`);
  }
  const { with_wettest_day: day, with_annual_rain: year } = correlation;
  if (day != null && year != null) {
    const leader = day >= year ? "the year's wettest day" : "the year's total rain";
    statTile(
      row,
      "Claims rise and fall with",
      leader,
      `Rank correlation over ${correlation.years} years: wettest day ${day.toFixed(2)}, total rain ${year.toFixed(2)} (1 = always together)`,
    );
  }
}

function renderTable(years) {
  const body = document.querySelector("#history-table tbody");
  body.replaceChildren();
  for (const y of [...years].reverse()) {
    const row = document.createElement("tr");
    const cells = [
      y.year,
      count(y.claims),
      y.paid ? `$${count(y.paid)}` : "$0",
      y.policies != null ? count(y.policies) : "",
      y.claims_per_1000_policies != null ? y.claims_per_1000_policies.toFixed(1) : "",
      y.rain_inches != null ? inches(y.rain_inches) : "—",
      y.wettest_day_inches != null ? inches(y.wettest_day_inches, 2) : "—",
      y.noaa_flood_events != null ? count(y.noaa_flood_events) : "",
      y.nws_flood_reports != null ? count(y.nws_flood_reports) : "",
      y.flood_event || "",
    ];
    cells.forEach((text, i) => {
      const cell = document.createElement(i === 0 ? "th" : "td");
      if (i === 0) cell.scope = "row";
      cell.textContent = text;
      row.append(cell);
    });
    body.append(row);
  }
}

function render() {
  const county = form.county.value;
  const metric = METRICS[form.metric.value];
  const history = histories[county];
  const years = history.years;
  const place = county === "all" ? "the four counties" : form.county.selectedOptions[0].textContent;

  document.getElementById("claims-title").textContent = `${metric.title}, ${place}`;
  document.getElementById("claims-note").textContent = metric.note;
  renderStats(history, years);
  renderTable(years);

  const charts = [];
  const onHover = (i, event) => {
    charts.forEach((chart) => chart.show(i));
    showTooltip(years[i], event);
  };
  const onLeave = () => {
    charts.forEach((chart) => chart.hide());
    tooltip.hidden = true;
  };
  const summary = (what, format) => (values) => {
    const present = values.map((v, i) => [v, years[i].year]).filter(([v]) => v != null);
    const [max, year] = present.reduce((best, item) => (item[0] > best[0] ? item : best), [-Infinity, null]);
    return `Column chart of ${what} for each year from ${years[0].year} to ${years.at(-1).year}; highest ${format(max)} in ${year}. Every value is in the table below.`;
  };

  charts.push(
    columnChart(document.getElementById("claims-chart"), years, {
      value: metric.value,
      color: COLORS.claims,
      format: metric.axis,
      labels: standoutYears(years, metric.value).map(({ index }) => ({ index, text: floodName(years[index]) })),
      describe: summary(metric.title.toLowerCase(), metric.axis),
      onHover,
      onLeave,
    }),
    columnChart(document.getElementById("rain-chart"), years, {
      value: (y) => y.rain_inches,
      color: COLORS.rain,
      format: (n) => String(n),
      describe: summary("inches of rain over the year", (n) => `${inches(n)} in`),
      onHover,
      onLeave,
    }),
    columnChart(document.getElementById("wettest-chart"), years, {
      value: (y) => y.wettest_day_inches,
      color: COLORS.wettest,
      format: (n) => String(n),
      describe: summary("inches of rain on the wettest day", (n) => `${inches(n, 2)} in`),
      onHover,
      onLeave,
    }),
  );
}

form.addEventListener("change", render);
render();
