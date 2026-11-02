import { postJson } from "./api.js";
import { mapReady } from "./map/main.js";

const root = document.querySelector("[data-wayfinder]");

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

function advisoryText(advisory) {
  return `${advisory.limitations.join(" ")} Last checked ${new Date(advisory.last_checked).toLocaleString()}.`;
}

function details(section, heading, text, links = []) {
  section.replaceChildren();
  section.classList.remove("hidden");
  const title = document.createElement("h3");
  title.className = "font-medium";
  title.textContent = heading;
  section.append(title);
  const message = document.createElement("p");
  message.className = "mt-1";
  message.textContent = text;
  section.append(message);
  if (links.length) {
    const conditions = document.createElement("p");
    conditions.className = "mt-1 text-muted";
    conditions.textContent = `Official conditions: ${links.join(", ")}`;
    section.append(conditions);
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
  const active = root.querySelector("[data-wayfinder-active]");
  const update = root.querySelector("[data-wayfinder-update]");
  let current = null;

  function updateControls() {
    const controls = document.createElement("div");
    controls.className = "mt-2 flex flex-wrap gap-2";
    const propose = document.createElement("button");
    propose.type = "button";
    propose.className = "rounded-md border border-line px-2 py-1 text-sm";
    propose.textContent = "Check for a proposed update";
    propose.addEventListener("click", async () => {
      if (!current) return;
      propose.disabled = true;
      details(update, "Proposed update", "Revalidating current official conditions…");
      try {
        const response = await postJson("wayfinder/advisories/updates", {
          active_advisory_id: current.id,
        });
        if (!response.proposal) {
          details(update, "No proposed update", response.outcome, response.cautions || []);
          return;
        }
        const candidate = response.proposal.advisory;
        details(update, "Proposed update (not active)", `${response.proposal.message} ${candidate.limitations.join(" ")}`, candidate.official_condition_links);
        const decisions = document.createElement("div");
        decisions.className = "mt-2 flex gap-2";
        const accept = document.createElement("button");
        accept.type = "button"; accept.className = "rounded-md bg-accent px-2 py-1 text-sm text-accent-ink"; accept.textContent = "Accept proposed route";
        const decline = document.createElement("button");
        decline.type = "button"; decline.className = "rounded-md border border-line px-2 py-1 text-sm"; decline.textContent = "Keep active route";
        accept.addEventListener("click", async () => {
          await draw(candidate.geometry);
          current = { ...current, id: `${current.id}-accepted`, advisory: candidate };
          details(active, "Active advisory", advisoryText(candidate), candidate.official_condition_links);
          details(update, "Proposed update accepted", "You explicitly selected this advisory. It remains an advisory, not navigation or a passability claim.");
        });
        decline.addEventListener("click", () => details(update, "Proposed update declined", "Your active advisory remains unchanged."));
        decisions.append(accept, decline); update.append(decisions);
      } catch (error) {
        details(update, "No proposed update", error.message || "The update could not be checked.");
      } finally {
        propose.disabled = false;
      }
    });
    controls.append(propose); active.append(controls);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const fields = new FormData(form);
      show(result, "Checking current official closure evidence…");
      const request = {
        origin: fields.get("origin"), destination: fields.get("destination"),
      };
      const advisory = await postJson("wayfinder/advisories", request);
      await draw(advisory.geometry);
      const message = advisory.status === "advisory"
        ? advisoryText(advisory)
        : `${advisory.reasons.join(" ")} ${advisory.limitations.join(" ")}`;
      show(result, message, advisory.official_condition_links);
      update.classList.add("hidden"); update.replaceChildren();
      if (advisory.status === "advisory") {
        current = { id: advisory.advisory_id, request, advisory };
        details(active, "Active advisory", advisoryText(advisory), advisory.official_condition_links);
        updateControls();
      } else {
        current = null; active.classList.add("hidden"); active.replaceChildren();
      }
    } catch (error) {
      await draw(null);
      show(result, error.message || "The advisory could not be checked.");
    }
  });
}
