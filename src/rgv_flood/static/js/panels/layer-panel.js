/* The layer panel, the active-layer legend and the source-details card.
 *
 * Built from /api/v1/layers. Layers that share a `panel_row` are one row whose
 * sub-options are those layers (TWDB 1% / 0.2%); a single layer with `parts`
 * gets one sub-option per part (photos you can open / locations only). A
 * group's checkbox turns its rows on or off together and shows a dash when
 * only some are on. State lives in Alpine.store("layers") so the legend and
 * the shareable link can read it. */

import { getJson, isAbort } from "../api.js";
import { hideLayer, setPartVisible, showLayer } from "../map/layers.js";
import { mapReady } from "../map/main.js";

/** Rows of a group: consecutive layers with the same panel_row become one row. */
function rowsOf(group) {
  const rows = [];
  for (const layer of group.layers) {
    const last = rows.at(-1);
    if (last && last.id === layer.panel_row) last.layers.push(layer);
    else rows.push({ id: layer.panel_row, label: layer.row_label, layers: [layer], group: group.id });
  }
  return rows.map((row) => ({
    ...row,
    count: row.layers.reduce((sum, layer) => sum + (layer.feature_count || 0), 0),
    legend: row.layers[0].legend,
  }));
}

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.store("layers", {
    groups: [], // [{id, title, rows}]
    on: {}, // layer id -> true while shown
    partsOff: {}, // "layer.part" -> true while that part is hidden
    details: null, // the layer whose source card is open
    get rows() {
      return this.groups.flatMap((group) => group.rows);
    },
    rowOn(row) {
      return row.layers.some((layer) => this.on[layer.id]);
    },
    get activeRows() {
      return this.rows.filter((row) => this.rowOn(row));
    },
    info(id) {
      return this.rows.flatMap((row) => row.layers).find((layer) => layer.id === id);
    },
    loaded: false,
    setLayer: (info, on) => setLayer(info, on), // for the shareable link
  });

  const store = () => Alpine.store("layers");

  async function setLayer(info, on) {
    store().on[info.id] = on;
    const map = await mapReady;
    if (!on) return hideLayer(map, info.id);
    Alpine.store("app").loading = true;
    try {
      await showLayer(map, info);
      for (const part of info.parts || []) {
        if (store().partsOff[`${info.id}.${part.id}`]) setPartVisible(map, info.id, part.id, false);
      }
      if (!store().on[info.id]) hideLayer(map, info.id); // turned off again while loading
    } catch (error) {
      if (!isAbort(error)) {
        console.warn("layer failed to load", info.id, error);
        store().on[info.id] = false;
      }
    } finally {
      Alpine.store("app").loading = false;
    }
  }

  Alpine.data("layerPanel", () => ({
    async init() {
      try {
        const body = await getJson("layers");
        store().groups = body.groups.map((group) => ({ id: group.id, title: group.title, rows: rowsOf(group) }));
        store().loaded = true;
        const map = await mapReady;
        for (const base of body.base) showLayer(map, base);
      } catch (error) {
        if (!isAbort(error)) console.warn("layer list unavailable", error);
      }
    },
    get groups() {
      return store().groups;
    },
    get activeCount() {
      return store().activeRows.length;
    },
    // --- inside x-for: `this.group`, `this.row`, `this.sub` come from the loop
    groupChecked() {
      return this.group.rows.every((row) => store().rowOn(row));
    },
    groupTally() {
      return `${this.group.rows.filter((row) => store().rowOn(row)).length}/${this.group.rows.length}`;
    },
    watchIndeterminate() {
      Alpine.effect(() => {
        const on = this.group.rows.filter((row) => store().rowOn(row)).length;
        this.$el.indeterminate = on > 0 && on < this.group.rows.length;
      });
    },
    toggleGroup() {
      const turnOn = !this.groupChecked();
      for (const row of this.group.rows) {
        for (const layer of row.layers) if (Boolean(store().on[layer.id]) !== turnOn) setLayer(layer, turnOn);
      }
    },
    rowChecked() {
      return store().rowOn(this.row);
    },
    toggleRow(event) {
      for (const layer of this.row.layers) setLayer(layer, event.target.checked);
    },
    subOptions() {
      if (!store().rowOn(this.row)) return [];
      if (this.row.layers.length > 1) {
        return this.row.layers.map((layer) => ({ id: layer.id, label: layer.short_label, layer }));
      }
      const layer = this.row.layers[0];
      return (layer.parts || []).map((part) => ({ id: part.id, label: part.label, layer, part }));
    },
    subChecked() {
      const { layer, part } = this.sub;
      return part ? !store().partsOff[`${layer.id}.${part.id}`] : Boolean(store().on[layer.id]);
    },
    async toggleSub(event) {
      const { layer, part } = this.sub;
      if (!part) return setLayer(layer, event.target.checked);
      const key = `${layer.id}.${part.id}`;
      if (event.target.checked) delete store().partsOff[key];
      else store().partsOff[key] = true;
      setPartVisible(await mapReady, layer.id, part.id, event.target.checked);
    },
    swatchClass() {
      return `sw sw-${this.row.legend.shape}`;
    },
    swatchStyle() {
      return `--sw: var(${COLOR_VARS[this.row.legend.color] || "--c-nfhl"})`;
    },
    rowCount() {
      return this.row.count ? this.row.count.toLocaleString() : "";
    },
    openDetails() {
      store().details = this.row.layers[0];
    },
  }));

  Alpine.data("legend", () => ({
    get rows() {
      return store().activeRows;
    },
    get claimsOn() {
      return Boolean(store().on["nfip-claims-by-tract"]);
    },
    swatchClass() {
      return `sw sw-${this.row.legend.shape}`;
    },
    swatchStyle() {
      return `--sw: var(${COLOR_VARS[this.row.legend.color] || "--c-nfhl"})`;
    },
    shortLabel() {
      return this.row.label.split(",")[0];
    },
  }));

  Alpine.data("sourceDetails", () => ({
    get layer() {
      return store().details;
    },
    get open() {
      return store().details !== null;
    },
    close() {
      store().details = null;
    },
  }));
});

// Legend color key -> CSS variable (the same tokens the map reads).
const COLOR_VARS = {
  nfhl: "--c-nfhl", firm: "--c-firm", twdb: "--c-twdb", drain: "--c-drain", infra: "--c-infra", city: "--c-city",
  hdrain: "--c-hdrain", bridge: "--c-bridge", mapped: "--c-mapped", photos: "--c-photos", fema: "--c-fema",
  nws: "--c-nws", proj: "--c-proj", sfp: "--c-sfp", claims: "--c-claims", county: "--county", dam: "--c-dam",
  "sev-high": "--sev-high", warn: "--warn",
};
