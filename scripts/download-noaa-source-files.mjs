#!/usr/bin/env node
/**
 * Download the raw NOAA files the ingest scripts need, so the full chain
 * (scaffold -> download -> ingest -> build) runs from a bare clone with no
 * manual downloading.
 *
 * Storm Events ships one file per year covering the whole country, so all four
 * counties share one directory; GHCN-Daily is one file per station, and each
 * county has its own station set (kept in sync with STATIONS_BY_COUNTY in
 * ingest-noaa-ghcn-daily.mjs -- update both if a station set changes).
 *
 * Idempotent: skips a file that's already present and non-empty.
 *
 * Usage: node scripts/download-noaa-source-files.mjs [output-dir]
 *   output-dir defaults to ./tmp/noaa (gitignored scratch space)
 */

import { mkdir, stat } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { Readable } from "node:stream";
import { finished } from "node:stream/promises";
import { join } from "node:path";

const OUT_DIR = process.argv[2] ?? "tmp/noaa";

const STORM_EVENTS_INDEX = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/";
const STORM_EVENTS_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles";
const GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station";
const FIRST_YEAR = 2000;
const LAST_YEAR = 2025;

// Station IDs only -- see ingest-noaa-ghcn-daily.mjs's STATIONS_BY_COUNTY for
// names/coordinates/elevations. Keep this list in sync with that one.
const GHCN_STATIONS_BY_COUNTY = {
  hidalgo: [
    "USW00012959", "USW00012987", "USC00412758", "USC00414139", "USC00415701",
    "USC00415836", "USC00415972", "USC00415973", "USC00419588",
  ],
  cameron: [
    "USW00012919", "USW00012904", "USW00012957", "USC00411133", "USC00413943",
    "USC00417952", "USC00410576", "USC00418060",
  ],
  starr: ["USC00417622", "USC00411349", "USC00412879", "USC00413060", "USC00413444"],
  willacy: ["USC00417458", "USC00415444", "USC00416017", "USC00417184", "USC00417990"],
};

async function alreadyDownloaded(path) {
  try {
    const info = await stat(path);
    return info.size > 0;
  } catch {
    return false;
  }
}

async function download(url, destPath) {
  if (await alreadyDownloaded(destPath)) {
    console.log(`  [skip] ${destPath} already present`);
    return;
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GET ${url} -> HTTP ${response.status}`);
  }
  const out = createWriteStream(destPath);
  await finished(Readable.fromWeb(response.body).pipe(out));
  console.log(`  [ok]   ${destPath}`);
}

async function stormEventsFileNames() {
  const response = await fetch(STORM_EVENTS_INDEX);
  if (!response.ok) {
    throw new Error(`GET ${STORM_EVENTS_INDEX} -> HTTP ${response.status}`);
  }
  const html = await response.text();
  const pattern = /StormEvents_details-ftp_v1\.0_d(20\d{2})_c\d+\.csv\.gz/g;
  const byYear = new Map();
  for (const match of html.matchAll(pattern)) {
    const year = Number(match[1]);
    if (year >= FIRST_YEAR && year <= LAST_YEAR) byYear.set(year, match[0]);
  }
  const missing = [];
  for (let year = FIRST_YEAR; year <= LAST_YEAR; year += 1) {
    if (!byYear.has(year)) missing.push(year);
  }
  if (missing.length) {
    throw new Error(`Storm Events index is missing year(s): ${missing.join(", ")}`);
  }
  return [...byYear.values()];
}

async function downloadStormEvents() {
  const dir = join(OUT_DIR, "storm-events");
  await mkdir(dir, { recursive: true });
  console.log(`Storm Events -> ${dir}`);
  const fileNames = await stormEventsFileNames();
  for (const fileName of fileNames) {
    await download(`${STORM_EVENTS_BASE}/${fileName}`, join(dir, fileName));
  }
  return dir;
}

async function downloadGhcn() {
  const dirsByCounty = {};
  for (const [county, stations] of Object.entries(GHCN_STATIONS_BY_COUNTY)) {
    const dir = join(OUT_DIR, `ghcn-${county}`);
    await mkdir(dir, { recursive: true });
    console.log(`GHCN-Daily (${county}) -> ${dir}`);
    for (const stationId of stations) {
      await download(`${GHCN_BASE}/${stationId}.csv.gz`, join(dir, `${stationId}.csv.gz`));
    }
    dirsByCounty[county] = dir;
  }
  return dirsByCounty;
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const stormEventsDir = await downloadStormEvents();
  const ghcnDirs = await downloadGhcn();
  console.log("\nDone. Ingest with, for each county:");
  console.log(
    `  node scripts/ingest-noaa-storm-events.mjs ${stormEventsDir} data/<slug>-county/records/events-and-public-reports/noaa-storm-events.ndjson data/<slug>-county/sources/official-events/noaa-storm-events-2000-2025.json <CZ_NAME>`,
  );
  for (const [county, dir] of Object.entries(ghcnDirs)) {
    console.log(
      `  node scripts/ingest-noaa-ghcn-daily.mjs ${dir} data/${county}-county/records/layers-and-weather/noaa-ghcn-daily-2000-2025.ndjson data/${county}-county/sources/weather/noaa-ghcn-daily-2000-2025.json ${county}`,
    );
  }
}

main().catch((error) => {
  console.error(error.message ?? error);
  process.exitCode = 1;
});
