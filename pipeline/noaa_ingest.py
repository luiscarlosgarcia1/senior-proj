#!/usr/bin/env python3
"""Download and ingest NOAA Storm Events and GHCN-Daily for the four RGV counties.

  download   fetch the raw .csv.gz files (skips any already present)
  ingest     turn them into each county's canonical ndjson + a source note
  (neither)  both, in order

Storm Events ships one file per year for the whole country, so each file is read
once and every county is filled from that single pass. GHCN-Daily is one file per
station, grouped by county in `noaa_stations.py`.

Each county gets, under data/<slug>-county/:
  records/events-and-public-reports/noaa-storm-events.ndjson
  sources/official-events/noaa-storm-events-2000-2025.json
  records/layers-and-weather/noaa-ghcn-daily-2000-2025.ndjson
  sources/weather/noaa-ghcn-daily-2000-2025.json

Run:  uv run python pipeline/noaa_ingest.py [download|ingest] [--county hidalgo] [--raw-dir tmp/noaa]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import shutil
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from noaa_stations import STATIONS_BY_COUNTY

from rgv_flood.counties import SHORT_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]

PUBLISHER = "NOAA National Centers for Environmental Information"
STORM_EVENTS_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles"
GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station"
FIRST_YEAR, LAST_YEAR = 2000, 2025
USER_AGENT = {"User-Agent": "RGV-Flood-Impact-Visualizer/1.0 (student research)"}

# Some Storm Events narratives are longer than the csv module's default field limit.
csv.field_size_limit(sys.maxsize)

STORM_FILE = re.compile(r"^StormEvents_details-ftp_v1\.0_d20\d{2}_c\d+\.csv\.gz$")
INCLUDED_EVENT_TYPES = {"Flood", "Flash Flood", "Heavy Rain", "Coastal Flood", "Lakeshore Flood", "Debris Flow"}

MONTHS = {
    name: f"{number:02d}"
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1
    )
}
GHCN_ELEMENTS = {"PRCP": "tenths of millimeters", "TMAX": "tenths of degrees Celsius",
                 "TMIN": "tenths of degrees Celsius", "AWND": "tenths of meters per second"}
GHCN_FIRST_DAY, GHCN_LAST_DAY = "20000101", "20251231"


# ---- helpers ----------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_number(value: float) -> int | float:
    """Print whole floats as integers (26.0 -> 26), as the source files always did."""
    return int(value) if value.is_integer() else value


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _write_ndjson(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_dump(r) + "\n" for r in records), encoding="utf-8")


def _write_note(path: Path, note: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(note, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _county_paths(data_dir: Path, slug: str) -> dict[str, Path]:
    county = data_dir / f"{slug}-county"
    return {
        "storm_records": county / "records" / "events-and-public-reports" / "noaa-storm-events.ndjson",
        "storm_note": county / "sources" / "official-events" / "noaa-storm-events-2000-2025.json",
        "ghcn_records": county / "records" / "layers-and-weather" / "noaa-ghcn-daily-2000-2025.ndjson",
        "ghcn_note": county / "sources" / "weather" / "noaa-ghcn-daily-2000-2025.json",
    }


# ---- download ---------------------------------------------------------------


def _download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest} already present")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(request, timeout=300) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out)
    part.replace(dest)
    print(f"  [ok]   {dest}")


def _storm_event_file_names() -> list[str]:
    """The newest detail file for each year, read from NOAA's directory listing."""
    request = urllib.request.Request(f"{STORM_EVENTS_BASE}/", headers=USER_AGENT)
    with urllib.request.urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8", errors="replace")
    by_year = {}
    for match in re.finditer(r"StormEvents_details-ftp_v1\.0_d(20\d{2})_c\d+\.csv\.gz", html):
        year = int(match.group(1))
        if FIRST_YEAR <= year <= LAST_YEAR:
            by_year[year] = match.group(0)
    missing = [y for y in range(FIRST_YEAR, LAST_YEAR + 1) if y not in by_year]
    if missing:
        raise RuntimeError(f"Storm Events index is missing year(s): {', '.join(map(str, missing))}")
    return list(by_year.values())


def download(raw_dir: Path, counties: list[str]) -> None:
    print(f"Storm Events -> {raw_dir / 'storm-events'}")
    for name in _storm_event_file_names():
        _download(f"{STORM_EVENTS_BASE}/{name}", raw_dir / "storm-events" / name)
    for slug in counties:
        print(f"GHCN-Daily ({slug}) -> {raw_dir / f'ghcn-{slug}'}")
        for station_id in STATIONS_BY_COUNTY[slug]:
            _download(f"{GHCN_BASE}/{station_id}.csv.gz", raw_dir / f"ghcn-{slug}" / f"{station_id}.csv.gz")


# ---- Storm Events -----------------------------------------------------------


def _event_date(date_time: str, year_month: str, day: str) -> str | None:
    """'21-JUN-18 ...' -> '2018-06-21'; falls back to YEARMONTH (YYYYMM) + DAY."""
    named = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{2})", date_time.strip())
    if named and named.group(2) in MONTHS:
        day_of_month, month, short_year = named.groups()
        century = "19" if int(short_year) >= 50 else "20"
        return f"{century}{short_year}-{MONTHS[month]}-{day_of_month.zfill(2)}"
    if re.fullmatch(r"\d{6}", year_month) and re.fullmatch(r"\d{1,2}", day):
        return f"{year_month[:4]}-{year_month[4:6]}-{day.zfill(2)}"
    return None


def _coordinate(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value != 0 else None


def _storm_record(row: dict[str, str], file_name: str, county_display: str, retrieved_at: str) -> dict | None:
    event_type = row["EVENT_TYPE"].strip()
    latitude, longitude = _coordinate(row["BEGIN_LAT"]), _coordinate(row["BEGIN_LON"])
    has_point = latitude is not None and longitude is not None
    start = _event_date(row["BEGIN_DATE_TIME"], row["BEGIN_YEARMONTH"], row["BEGIN_DAY"])
    event_id = row["EVENT_ID"].strip()
    if not start or not event_id:
        return None

    location = row["BEGIN_LOCATION"].strip()
    narrative = row["EVENT_NARRATIVE"].strip()
    year = re.search(r"_d(\d{4})_", file_name).group(1)
    where = f" near {location}" if location else f" in {county_display} County"
    summary = f"NOAA Storm Events {event_type.lower()} record{where}."
    record = {
        "record_id": f"noaa-storm-events-{event_id}",
        "source_publisher": PUBLISHER,
        "source_channel": "official_dataset",
        "source_reference": {"kind": "source_url", "value": f"{STORM_EVENTS_BASE}/{file_name}"},
        "published_at": None,
        "event_start": start,
        "event_end": _event_date(row["END_DATE_TIME"], row["END_YEARMONTH"], row["END_DAY"]),
        "location_text": f"{location}, {county_display} County, Texas" if location else f"{county_display} County, Texas",
        "geometry": {"type": "Point", "coordinates": [_json_number(longitude), _json_number(latitude)]} if has_point else None,
        "location_precision": "exact" if has_point else "county",
    }
    if not has_point:
        record["geometry_absence_reason"] = "NOAA Storm Events detail row has no usable beginning latitude/longitude."
    record.update({
        "record_kind": "flood_event",
        "summary": f"{summary} {narrative}" if narrative else summary,
        "original_content_reference": narrative
        or row["EPISODE_NARRATIVE"].strip()
        or f"NOAA Storm Events event ID {event_id} ({event_type}; {year}).",
        "duplicate_group_id": None,
        "retrieved_at": retrieved_at,
    })
    return record


def _read_storm_file(path: Path, counties_by_cz_name: dict[str, str], retrieved_at: str) -> dict[str, list[dict]]:
    """Flood-event records from one annual file, grouped by county slug."""
    found: dict[str, list[dict]] = {slug: [] for slug in counties_by_cz_name.values()}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        header = [column.strip() for column in next(reader)]
        index = {column: i for i, column in enumerate(header)}
        state_col, county_col, type_col = index["STATE"], index["CZ_NAME"], index["EVENT_TYPE"]
        for cells in reader:
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            slug = counties_by_cz_name.get(cells[county_col].strip())
            if slug is None or cells[state_col].strip() != "TEXAS" or cells[type_col].strip() not in INCLUDED_EVENT_TYPES:
                continue
            record = _storm_record(dict(zip(header, cells[: len(header)], strict=True)), path.name, SHORT_NAMES[slug], retrieved_at)
            if record:
                found[slug].append(record)
    return found


def _existing_non_generated(path: Path) -> list[dict]:
    """Hand-curated rows (e.g. Hidalgo's news and government reports) that no script
    can reproduce. Re-running the ingest must not delete them."""
    if not path.exists():
        return []
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return [row for row in rows if row.get("record_kind") != "flood_event"]


def ingest_storm_events(raw_dir: Path, data_dir: Path, counties: list[str]) -> None:
    retrieved_at = _now()
    files = sorted(p.name for p in (raw_dir / "storm-events").iterdir() if STORM_FILE.match(p.name))
    by_cz_name = {SHORT_NAMES[slug].upper(): slug for slug in counties}
    generated: dict[str, list[dict]] = {slug: [] for slug in counties}
    for name in files:
        for slug, records in _read_storm_file(raw_dir / "storm-events" / name, by_cz_name, retrieved_at).items():
            generated[slug] += records

    for slug in counties:
        paths = _county_paths(data_dir, slug)
        preserved = _existing_non_generated(paths["storm_records"])
        if preserved:
            print(f"[preserve] keeping {len(preserved)} existing non-generated record(s) from {paths['storm_records']}")
        records = sorted(generated[slug] + preserved, key=lambda r: (r["event_start"], r["record_id"]))
        _write_ndjson(paths["storm_records"], records)
        cz_name = SHORT_NAMES[slug].upper()
        _write_note(paths["storm_note"], {
            "publisher": PUBLISHER,
            "dataset": "Storm Events Database",
            "retrieved_at": retrieved_at,
            "annual_detail_files": [f"{STORM_EVENTS_BASE}/{name}" for name in files],
            "filter": {
                "state": "TEXAS",
                "county": cz_name,
                "county_or_zone_name": cz_name,
                "event_types": sorted(INCLUDED_EVENT_TYPES),
            },
            "retained_record_count": len(records),
            "notes": "Storm Events detail rows are official documented events. Their stated location precision and coordinates are retained without inference.",
        })
        print(json.dumps({"county": slug, "files": len(files), "records": len(records)}))


# ---- GHCN-Daily -------------------------------------------------------------


def _ghcn_number(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text) if text.strip() else 0


def _ghcn_observation(element: str, value: str, measurement: str, quality: str, source: str, time_flag: str) -> dict:
    return {
        "value": _ghcn_number(value),
        "unit": GHCN_ELEMENTS[element],
        "measurement_flag": measurement or None,
        "quality_flag": quality or None,
        "source_flag": source or None,
        "observation_time_flag": time_flag or None,
    }


def _read_station(path: Path, station_id: str) -> dict[str, dict]:
    """date (YYYYMMDD) -> {element: observation} for the retained elements, 2000-2025,
    skipping any row NOAA flagged for quality."""
    by_date: dict[str, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.strip().split(",") + [""] * 8
            ident, date, element, value, measurement, quality, source, time_flag = fields[:8]
            if ident != station_id or not (GHCN_FIRST_DAY <= date <= GHCN_LAST_DAY) or element not in GHCN_ELEMENTS or quality:
                continue
            by_date.setdefault(date, {})[element] = _ghcn_observation(element, value, measurement, quality, source, time_flag)
    return by_date


def ingest_ghcn_daily(raw_dir: Path, data_dir: Path, counties: list[str]) -> None:
    retrieved_at = _now()
    for slug in counties:
        stations = STATIONS_BY_COUNTY[slug]
        records = []
        for path in sorted((raw_dir / f"ghcn-{slug}").glob("*.csv.gz")):
            station_id = path.name.removesuffix(".csv.gz")
            station = stations.get(station_id)
            if not station:
                continue
            for date, observations in _read_station(path, station_id).items():
                iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                records.append({
                    "record_id": f"noaa-ghcn-daily-{station_id.lower()}-{iso_date}",
                    "record_kind": "weather_observation",
                    "source_reference": {"kind": "api_endpoint", "value": f"{GHCN_BASE}/{path.name}"},
                    "source_publisher": PUBLISHER,
                    "dataset_name": "Global Historical Climatology Network Daily (GHCN-Daily)",
                    "dataset_version_or_publication_date": "Current GHCN-Daily archive snapshot",
                    "retrieved_at": retrieved_at,
                    "coverage_or_station_geometry": {
                        "type": "Point",
                        "coordinates": [_json_number(station["longitude"]), _json_number(station["latitude"])],
                    },
                    "original_attributes": {
                        "station_id": station_id,
                        "station_name": station["name"],
                        "station_elevation_m": station["elevation_m"],
                        "date": iso_date,
                        "observations": observations,
                    },
                    "license_or_terms_note": "NOAA public data; retain NOAA source provenance and applicable source terms.",
                })
        records.sort(key=lambda r: r["record_id"])

        paths = _county_paths(data_dir, slug)
        _write_ndjson(paths["ghcn_records"], records)
        with_data = sorted({r["original_attributes"]["station_id"] for r in records})
        _write_note(paths["ghcn_note"], {
            "publisher": PUBLISHER,
            "dataset": "Global Historical Climatology Network Daily (GHCN-Daily)",
            "retrieved_at": retrieved_at,
            "temporal_coverage_requested": "2000-01-01 through 2025-12-31",
            "retained_elements": {
                "PRCP": "daily precipitation (tenths of millimeters)",
                "TMAX": "daily maximum temperature (tenths of degrees Celsius)",
                "TMIN": "daily minimum temperature (tenths of degrees Celsius)",
                "AWND": "daily average wind speed (tenths of meters per second)",
            },
            "station_files": [
                {"station_id": sid, **station, "url": f"{GHCN_BASE}/{sid}.csv.gz"} for sid, station in stations.items()
            ],
            "stations_with_retained_observations": with_data,
            "retained_record_count": len(records),
            "notes": "Rows with a nonblank NOAA quality flag are excluded. Values and remaining NOAA flags are preserved without unit conversion.",
        })
        print(json.dumps({"county": slug, "requested_stations": len(stations),
                          "stations_with_retained_observations": len(with_data), "records": len(records)}))


# ---- command line -----------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", nargs="?", choices=("download", "ingest"), help="default: both")
    parser.add_argument("--county", choices=sorted(SHORT_NAMES), help="limit to one county (default: all four)")
    parser.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "tmp" / "noaa", help="downloaded .csv.gz files")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data", help="where data/<county>-county/ lives")
    args = parser.parse_args()

    counties = [args.county] if args.county else sorted(SHORT_NAMES)
    if args.step in (None, "download"):
        download(args.raw_dir, counties)
    if args.step in (None, "ingest"):
        ingest_storm_events(args.raw_dir, args.data_dir, counties)
        ingest_ghcn_daily(args.raw_dir, args.data_dir, counties)


if __name__ == "__main__":
    main()
