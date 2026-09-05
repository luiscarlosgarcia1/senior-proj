#!/usr/bin/env node

import { gunzipSync } from "node:zlib";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const [inputDirectory, outputFile, sourceNoteFile] = process.argv.slice(2);
if (!inputDirectory || !outputFile || !sourceNoteFile) {
  throw new Error("Usage: node ingest-noaa-ghcn-daily.mjs <gzip-directory> <output.ndjson> <source-note.json>");
}

const SOURCE_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station";
const STATIONS = {
  USW00012959: { name: "McAllen Miller International Airport", latitude: 26.1792, longitude: -98.2444, elevation_m: 30.2 },
  USW00012987: { name: "Edinburg 17 NNE", latitude: 26.5258, longitude: -98.0633, elevation_m: 19.5 },
  USC00412758: { name: "Edinburg", latitude: 26.2981, longitude: -98.1575, elevation_m: 29.3 },
  USC00414139: { name: "Hidalgo", latitude: 26.1, longitude: -98.2667, elevation_m: 31.1 },
  USC00415701: { name: "McAllen", latitude: 26.1922, longitude: -98.2503, elevation_m: 33.5 },
  USC00415836: { name: "Mercedes 6 SSE", latitude: 26.0619, longitude: -97.8997, elevation_m: 22.9 },
  USC00415972: { name: "Mission 4 W", latitude: 26.2167, longitude: -98.4, elevation_m: 40.5 },
  USC00415973: { name: "Mission Pumping Station", latitude: 26.2, longitude: -98.3167, elevation_m: 39.9 },
  USC00419588: { name: "Weslaco", latitude: 26.1781, longitude: -97.9708, elevation_m: 22.9 },
};
const RETAINED_ELEMENTS = new Set(["PRCP", "TMAX", "TMIN", "AWND"]);

function attributesFor(element, value, measurementFlag, qualityFlag, sourceFlag, observationTimeFlag) {
  const unit = element === "PRCP" ? "tenths of millimeters" : element === "AWND" ? "tenths of meters per second" : "tenths of degrees Celsius";
  return {
    value: Number(value),
    unit,
    measurement_flag: measurementFlag || null,
    quality_flag: qualityFlag || null,
    source_flag: sourceFlag || null,
    observation_time_flag: observationTimeFlag || null,
  };
}

const retrievedAt = new Date().toISOString();
const recordsByStation = [];
for (const fileName of (await readdir(inputDirectory)).filter((name) => name.endsWith(".csv.gz")).sort()) {
  const stationId = fileName.replace(/\.csv\.gz$/, "");
  const station = STATIONS[stationId];
  if (!station) continue;
  const observations = new Map();
  const lines = gunzipSync(await readFile(join(inputDirectory, fileName))).toString("utf8").trim().split("\n");
  for (const line of lines) {
    const [id, date, element, value, measurementFlag, qualityFlag, sourceFlag, observationTimeFlag] = line.trim().split(",");
    if (id !== stationId || date < "20000101" || date > "20251231" || !RETAINED_ELEMENTS.has(element) || qualityFlag) continue;
    const observation = observations.get(date) ?? {};
    observation[element] = attributesFor(element, value, measurementFlag, qualityFlag, sourceFlag, observationTimeFlag);
    observations.set(date, observation);
  }
  for (const [date, originalAttributes] of observations) {
    const isoDate = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`;
    recordsByStation.push({
      record_id: `noaa-ghcn-daily-${stationId.toLowerCase()}-${isoDate}`,
      record_kind: "weather_observation",
      source_reference: { kind: "api_endpoint", value: `${SOURCE_BASE}/${fileName}` },
      source_publisher: "NOAA National Centers for Environmental Information",
      dataset_name: "Global Historical Climatology Network Daily (GHCN-Daily)",
      dataset_version_or_publication_date: "Current GHCN-Daily archive snapshot",
      retrieved_at: retrievedAt,
      coverage_or_station_geometry: { type: "Point", coordinates: [station.longitude, station.latitude] },
      original_attributes: {
        station_id: stationId,
        station_name: station.name,
        station_elevation_m: station.elevation_m,
        date: isoDate,
        observations: originalAttributes,
      },
      license_or_terms_note: "NOAA public data; retain NOAA source provenance and applicable source terms.",
    });
  }
}

recordsByStation.sort((left, right) => left.record_id.localeCompare(right.record_id));
const stationsWithRetainedObservations = [...new Set(recordsByStation.map((record) => record.original_attributes.station_id))].sort();
await writeFile(outputFile, `${recordsByStation.map((record) => JSON.stringify(record)).join("\n")}\n`);
await writeFile(sourceNoteFile, `${JSON.stringify({
  publisher: "NOAA National Centers for Environmental Information",
  dataset: "Global Historical Climatology Network Daily (GHCN-Daily)",
  retrieved_at: retrievedAt,
  temporal_coverage_requested: "2000-01-01 through 2025-12-31",
  retained_elements: {
    PRCP: "daily precipitation (tenths of millimeters)",
    TMAX: "daily maximum temperature (tenths of degrees Celsius)",
    TMIN: "daily minimum temperature (tenths of degrees Celsius)",
    AWND: "daily average wind speed (tenths of meters per second)",
  },
  station_files: Object.entries(STATIONS).map(([stationId, station]) => ({ station_id: stationId, ...station, url: `${SOURCE_BASE}/${stationId}.csv.gz` })),
  stations_with_retained_observations: stationsWithRetainedObservations,
  retained_record_count: recordsByStation.length,
  notes: "Rows with a nonblank NOAA quality flag are excluded. Values and remaining NOAA flags are preserved without unit conversion.",
}, null, 2)}\n`);
console.log(JSON.stringify({ requested_stations: Object.keys(STATIONS).length, stations_with_retained_observations: stationsWithRetainedObservations.length, records: recordsByStation.length }));
