#!/usr/bin/env node

import { createReadStream } from "node:fs";
import { readdir, writeFile } from "node:fs/promises";
import { createGunzip } from "node:zlib";
import { createInterface } from "node:readline";
import { join } from "node:path";

const [inputDirectory, outputFile, sourceNoteFile] = process.argv.slice(2);

if (!inputDirectory || !outputFile || !sourceNoteFile) {
  throw new Error(
    "Usage: node ingest-noaa-storm-events.mjs <gzip-directory> <output.ndjson> <source-note.json>",
  );
}

const SOURCE_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles";
const INCLUDED_EVENT_TYPES = new Set([
  "Flood",
  "Flash Flood",
  "Heavy Rain",
  "Coastal Flood",
  "Lakeshore Flood",
  "Debris Flow",
]);

function parseCsvLine(line) {
  const values = [];
  let value = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      values.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  values.push(value);
  return values;
}

function eventDate(dateTime, fallbackYearMonth, fallbackDay) {
  const dateText = dateTime?.trim();
  const namedDate = /^(\d{1,2})-([A-Z]{3})-(\d{2})/.exec(dateText ?? "");
  if (namedDate) {
    const [, day, monthName, shortYear] = namedDate;
    const months = { JAN: "01", FEB: "02", MAR: "03", APR: "04", MAY: "05", JUN: "06", JUL: "07", AUG: "08", SEP: "09", OCT: "10", NOV: "11", DEC: "12" };
    const year = Number(shortYear) >= 50 ? `19${shortYear}` : `20${shortYear}`;
    return `${year}-${months[monthName]}-${day.padStart(2, "0")}`;
  }
  if (/^\d{8}$/.test(fallbackYearMonth ?? "") && /^\d{1,2}$/.test(fallbackDay ?? "")) {
    return `${fallbackYearMonth.slice(0, 4)}-${fallbackYearMonth.slice(4, 6)}-${fallbackDay.padStart(2, "0")}`;
  }
  return null;
}

function finiteCoordinate(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed !== 0 ? parsed : null;
}

async function parseDetailsFile(fileName, retrievedAt) {
  const stream = createReadStream(join(inputDirectory, fileName)).pipe(createGunzip());
  const reader = createInterface({ input: stream, crlfDelay: Infinity });
  let header;
  const records = [];

  for await (const line of reader) {
    if (!header) {
      header = parseCsvLine(line).map((column) => column.trim());
      continue;
    }
    const cells = parseCsvLine(line);
    const row = Object.fromEntries(header.map((column, index) => [column, cells[index] ?? ""]));
    if (row.STATE?.trim() !== "TEXAS" || row.CZ_NAME?.trim() !== "HIDALGO") continue;
    if (!INCLUDED_EVENT_TYPES.has(row.EVENT_TYPE?.trim())) continue;

    const latitude = finiteCoordinate(row.BEGIN_LAT);
    const longitude = finiteCoordinate(row.BEGIN_LON);
    const hasGeometry = latitude !== null && longitude !== null;
    const start = eventDate(row.BEGIN_DATE_TIME, row.BEGIN_YEARMONTH, row.BEGIN_DAY);
    if (!start || !row.EVENT_ID?.trim()) continue;

    const eventType = row.EVENT_TYPE.trim();
    const location = row.BEGIN_LOCATION?.trim();
    const narrative = row.EVENT_NARRATIVE?.trim();
    const episodeNarrative = row.EPISODE_NARRATIVE?.trim();
    const sourceUrl = `${SOURCE_BASE}/${fileName}`;
    const year = fileName.match(/_d(\d{4})_/)?.[1];
    const summaryParts = [`NOAA Storm Events ${eventType.toLowerCase()} record${location ? ` near ${location}` : " in Hidalgo County"}.`];
    if (narrative) summaryParts.push(narrative);

    records.push({
      record_id: `noaa-storm-events-${row.EVENT_ID.trim()}`,
      source_publisher: "NOAA National Centers for Environmental Information",
      source_channel: "official_dataset",
      source_reference: { kind: "source_url", value: sourceUrl },
      published_at: null,
      event_start: start,
      event_end: eventDate(row.END_DATE_TIME, row.END_YEARMONTH, row.END_DAY),
      location_text: location ? `${location}, Hidalgo County, Texas` : "Hidalgo County, Texas",
      geometry: hasGeometry ? { type: "Point", coordinates: [longitude, latitude] } : null,
      location_precision: hasGeometry ? "exact" : "county",
      ...(hasGeometry ? {} : { geometry_absence_reason: "NOAA Storm Events detail row has no usable beginning latitude/longitude." }),
      record_kind: "flood_event",
      summary: summaryParts.join(" "),
      original_content_reference: narrative || episodeNarrative || `NOAA Storm Events event ID ${row.EVENT_ID.trim()} (${eventType}; ${year}).`,
      duplicate_group_id: null,
      retrieved_at: retrievedAt,
    });
  }

  return records;
}

const retrievedAt = new Date().toISOString();
const files = (await readdir(inputDirectory))
  .filter((fileName) => /^StormEvents_details-ftp_v1\.0_d20\d{2}_c\d+\.csv\.gz$/.test(fileName))
  .sort();
const records = (await Promise.all(files.map((fileName) => parseDetailsFile(fileName, retrievedAt)))).flat();
records.sort((left, right) => left.event_start.localeCompare(right.event_start) || left.record_id.localeCompare(right.record_id));

await writeFile(outputFile, `${records.map((record) => JSON.stringify(record)).join("\n")}\n`);
await writeFile(sourceNoteFile, `${JSON.stringify({
  publisher: "NOAA National Centers for Environmental Information",
  dataset: "Storm Events Database",
  retrieved_at: retrievedAt,
  annual_detail_files: files.map((fileName) => `${SOURCE_BASE}/${fileName}`),
  filter: {
    state: "TEXAS",
    county: "HIDALGO",
    county_or_zone_name: "HIDALGO",
    event_types: [...INCLUDED_EVENT_TYPES].sort(),
  },
  retained_record_count: records.length,
  notes: "Storm Events detail rows are official documented events. Their stated location precision and coordinates are retained without inference.",
}, null, 2)}\n`);

console.log(JSON.stringify({ files: files.length, records: records.length, outputFile, sourceNoteFile }));
