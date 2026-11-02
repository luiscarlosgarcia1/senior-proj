import { postJson } from "./api.js";
import { mapReady } from "./map/main.js";

const root = document.querySelector("[data-wayfinder]");

function point(value) {
  const [latitude, longitude, ...extra] = value.split(",").map(Number);
  if (extra.length || !Number.isFinite(latitude) || !Number.isFinite(longitude)) throw new Error("Use coordinates as latitude, longitude.");
  return { latitude, longitude };
}

function show(result, text, links = []) {
  result.replaceChildren();
  const message = document.createElement("p");
  message.textContent = text;
  result.append(message);
  if (links.length) {
    const list = document.createElement("ul");
    list.className = "mt-2 list-disc pl-5 text-muted";
    for (const href of links) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = href; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = "Official conditions";
      item.append(link); list.append(item);
    }
    result.append(list);
  }
}

async function draw(geometry) {
  const map = await mapReady;
  const source = "wayfinder-advisory";
  if (map.getLayer("wayfinder-advisory-line")) map.removeLayer("wayfinder-advisory-line");
  if (map.getSource(source)) map.removeSource(source);
  if (!geometry) return;
  map.addSource(source, { type: "geojson", data: { type: "Feature", properties: {}, geometry } });
  map.addLayer({ id: "wayfinder-advisory-line", type: "line", source, paint: { "line-color": "#cb4900", "line-width": 5, "line-opacity": 0.9 } });
}

if (root) {
  const form = root.querySelector("[data-wayfinder-form]");
  const result = root.querySelector("[data-wayfinder-result]");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const fields = new FormData(form);
      show(result, "Checking current official closure evidence…");
      const advisory = await postJson("wayfinder/advisories", {
        origin: point(fields.get("origin")), destination: point(fields.get("destination")),
      });
      await draw(advisory.geometry);
      const message = advisory.status === "advisory"
        ? `${advisory.limitations.join(" ")} Last checked ${new Date(advisory.last_checked).toLocaleString()}.`
        : `${advisory.reasons.join(" ")} ${advisory.limitations.join(" ")}`;
      show(result, message, advisory.official_condition_links);
    } catch (error) {
      await draw(null);
      show(result, error.message || "The advisory could not be checked.");
    }
  });
}
