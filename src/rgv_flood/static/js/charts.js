/* What the chart pages (claims, trends, news) share: the theme's colors, the layout every Plotly chart starts
 * from, drawing a chart, and a few small formatters. */

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A theme color (a CSS custom property such as "--line"), read now so a theme switch redraws in the new colors. */
export const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const sum = (numbers) => numbers.reduce((total, n) => total + n, 0);
/** "hidalgo" -> "Hidalgo". */
export const capitalized = (slug) => slug.charAt(0).toUpperCase() + slug.slice(1);

/** The layout every chart starts from: transparent background, the theme's font, hover label and colors. */
export function baseLayout(height, margin) {
  const ink = token("--text");
  return {
    height,
    margin,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    hoverlabel: { bgcolor: token("--panel2"), bordercolor: token("--accent"), font: { color: ink, family: "Public Sans", size: 11 } },
    font: { family: "Public Sans", size: 10, color: token("--muted") },
  };
}

/** Draw (or redraw in place) one chart, without Plotly's toolbar. */
export function drawChart(element, data, layout) {
  window.Plotly.react(element, data, layout, { displayModeBar: false, responsive: true });
}
