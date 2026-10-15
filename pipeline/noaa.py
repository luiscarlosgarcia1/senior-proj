"""Read NOAA Storm Events and GHCN-Daily into rows for the central database.

Storm Events ships one file per year for the whole country, so each file is read
once and every county is filled from that single pass. GHCN-Daily is one file per
station, grouped by county in `noaa_stations.py`.

Nothing here writes data files: `download_raw_files` keeps NOAA's own .csv.gz
files in the download cache, and the other functions read those straight into
memory as rows for the `flood_events`, `weather_stations` and
`weather_observations` tables (see `database.py`). `build_events.py` is what
calls them and writes the database.
"""

from __future__ import annotations

import csv
import gzip
import math
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from net import download, fetched_at, get_text
from noaa_stations import STATIONS_BY_COUNTY
from paths import DOWNLOAD_CACHE

from rgv_flood.counties import SHORT_NAMES

RAW_DIR = DOWNLOAD_CACHE / "noaa"
PUBLISHER = "NOAA National Centers for Environmental Information"
STORM_EVENTS_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles"
GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station"
LAST_YEAR = 2025
# The Storm Events Database has recorded flood events since 1996; before that it
# kept only tornadoes, thunderstorm wind and hail.
STORM_FIRST_YEAR = 1996
# The first year of FEMA's NFIP claims. Every county has a long-running rain
# gauge reaching that far back, so yearly rain can be set beside yearly claims.
GHCN_FIRST_YEAR = 1978

# Some Storm Events narratives are longer than the csv module's default field limit.
csv.field_size_limit(sys.maxsize)

STORM_FILE = re.compile(r"^StormEvents_details-ftp_v1\.0_d(\d{4})_c\d+\.csv\.gz$")
FLOOD_EVENT_TYPES = {"Flood", "Flash Flood", "Heavy Rain", "Coastal Flood", "Lakeshore Flood", "Debris Flow"}

MONTHS = {
    name: f"{number:02d}"
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1
    )
}
GHCN_ELEMENTS = ("PRCP", "TMAX", "TMIN", "AWND")
GHCN_FIRST_DAY, GHCN_LAST_DAY = f"{GHCN_FIRST_YEAR}0101", f"{LAST_YEAR}1231"


# ---- download ---------------------------------------------------------------


def _storm_event_file_names() -> list[str]:
    """The newest detail file for each year, read from NOAA's directory listing."""
    html = get_text(f"{STORM_EVENTS_BASE}/")
    by_year = {}
    for match in re.finditer(r"StormEvents_details-ftp_v1\.0_d(\d{4})_c\d+\.csv\.gz", html):
        year = int(match.group(1))
        if STORM_FIRST_YEAR <= year <= LAST_YEAR:
            by_year[year] = match.group(0)
    missing = [y for y in range(STORM_FIRST_YEAR, LAST_YEAR + 1) if y not in by_year]
    if missing:
        raise RuntimeError(f"Storm Events index is missing year(s): {', '.join(map(str, missing))}")
    return list(by_year.values())


def _storm_files(raw_dir: Path) -> list[Path]:
    """The cached yearly Storm Events files inside the window."""
    directory = raw_dir / "storm-events"
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir()
        if (match := STORM_FILE.match(path.name)) and STORM_FIRST_YEAR <= int(match.group(1)) <= LAST_YEAR
    )


def _station_file(raw_dir: Path, slug: str, station_id: str) -> Path:
    return raw_dir / f"ghcn-{slug}" / f"{station_id}.csv.gz"


def download_raw_files(counties: list[str], raw_dir: Path = RAW_DIR) -> None:
    """Fetch NOAA's files into the cache, skipping any already there.

    A complete set of yearly Storm Events files is not re-checked against
    NOAA's listing, so a cached build works offline.
    """
    years = {int(STORM_FILE.match(path.name).group(1)) for path in _storm_files(raw_dir)}
    if years >= set(range(STORM_FIRST_YEAR, LAST_YEAR + 1)):
        print(f"Storm Events: all {len(years)} yearly files already in {raw_dir / 'storm-events'}")
    else:
        print(f"Storm Events -> {raw_dir / 'storm-events'}")
        for name in _storm_event_file_names():
            download(f"{STORM_EVENTS_BASE}/{name}", raw_dir / "storm-events" / name)
    for slug in counties:
        print(f"GHCN-Daily ({slug}) -> {raw_dir / f'ghcn-{slug}'}")
        for station_id in STATIONS_BY_COUNTY[slug]:
            download(f"{GHCN_BASE}/{station_id}.csv.gz", _station_file(raw_dir, slug, station_id))


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


def _storm_event(row: dict[str, str], file_name: str, slug: str) -> dict | None:
    """One Storm Events detail row as a `flood_events` row, except for the
    plotted lon/lat and geometry_note, which `build_events.py` decides."""
    event_id = row["EVENT_ID"].strip()
    date = _event_date(row["BEGIN_DATE_TIME"], row["BEGIN_YEARMONTH"], row["BEGIN_DAY"])
    if not date or not event_id:
        return None

    county = SHORT_NAMES[slug]
    event_type = row["EVENT_TYPE"].strip()
    latitude, longitude = _coordinate(row["BEGIN_LAT"]), _coordinate(row["BEGIN_LON"])
    has_point = latitude is not None and longitude is not None
    place = row["BEGIN_LOCATION"].strip()
    narrative = row["EVENT_NARRATIVE"].strip()
    where = f" near {place}" if place else f" in {county} County"
    summary = f"NOAA Storm Events {event_type.lower()} record{where}."
    year = STORM_FILE.match(file_name).group(1)
    return {
        "id": f"noaa-storm-events-{event_id}",
        "county": slug,
        "date": date,
        "date_end": _event_date(row["END_DATE_TIME"], row["END_YEARMONTH"], row["END_DAY"]),
        "type": event_type.capitalize(),  # NOAA's own event type: "Flash Flood" -> "Flash flood"
        "location": f"{place}, {county} County, Texas" if place else f"{county} County, Texas",
        "precision": "exact" if has_point else "county",
        "summary": f"{summary} {narrative}" if narrative else summary,
        "narrative": narrative
        or row["EPISODE_NARRATIVE"].strip()
        or f"NOAA Storm Events event ID {event_id} ({event_type}; {year}).",
        "source_url": f"{STORM_EVENTS_BASE}/{file_name}",
        "source_lon": longitude if has_point else None,
        "source_lat": latitude if has_point else None,
    }


def _read_storm_file(path: Path, slug_by_cz_name: dict[str, str]) -> Iterator[dict]:
    """The flood-type events in one annual file that belong to the wanted counties."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        header = [column.strip() for column in next(reader)]
        index = {column: i for i, column in enumerate(header)}
        state_col, county_col, type_col = index["STATE"], index["CZ_NAME"], index["EVENT_TYPE"]
        for cells in reader:
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            slug = slug_by_cz_name.get(cells[county_col].strip())
            if slug is None or cells[state_col].strip() != "TEXAS" or cells[type_col].strip() not in FLOOD_EVENT_TYPES:
                continue
            event = _storm_event(dict(zip(header, cells[: len(header)], strict=True)), path.name, slug)
            if event:
                yield event


def storm_events(counties: list[str], raw_dir: Path = RAW_DIR) -> list[dict]:
    """Every flood-type Storm Events record for the counties, 1996 on."""
    slug_by_cz_name = {SHORT_NAMES[slug].upper(): slug for slug in counties}
    return [event for path in _storm_files(raw_dir) for event in _read_storm_file(path, slug_by_cz_name)]


def storm_events_source(count: int, raw_dir: Path = RAW_DIR) -> dict:
    """The `data_sources` row describing what `storm_events` read."""
    files = _storm_files(raw_dir)
    return {
        "id": "noaa-storm-events",
        "publisher": PUBLISHER,
        "dataset": "Storm Events Database",
        "url": f"{STORM_EVENTS_BASE}/",
        "retrieved_at": fetched_at(files),
        "record_count": count,
        "notes": (
            f"{len(files)} annual detail files, {STORM_FIRST_YEAR}-{LAST_YEAR}; Texas rows for the four counties with "
            f"event type {', '.join(sorted(FLOOD_EVENT_TYPES))}. Stated locations and coordinates are kept as published."
        ),
    }


# ---- GHCN-Daily -------------------------------------------------------------


def weather_stations(counties: list[str]) -> list[dict]:
    """`weather_stations` rows for every station assigned to the counties."""
    return [
        {
            "station_id": station_id,
            "county": slug,
            "name": station["name"],
            "lon": station["longitude"],
            "lat": station["latitude"],
            "elevation_m": station["elevation_m"],
            "source_url": f"{GHCN_BASE}/{station_id}.csv.gz",
        }
        for slug in counties
        for station_id, station in STATIONS_BY_COUNTY[slug].items()
    ]


def _number(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text) if text.strip() else 0


def _read_station(path: Path, station_id: str) -> Iterator[dict]:
    """`weather_observations` rows from one station file: the retained elements,
    1978 on, skipping any reading NOAA flagged for quality."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.strip().split(",") + [""] * 8
            ident, date, element, value, measurement, quality, source, time_flag = fields[:8]
            if ident != station_id or not (GHCN_FIRST_DAY <= date <= GHCN_LAST_DAY) or element not in GHCN_ELEMENTS or quality:
                continue
            yield {
                "station_id": station_id,
                "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
                "element": element,
                "value": _number(value),
                "measurement_flag": measurement or None,
                "source_flag": source or None,
                "observation_time_flag": time_flag or None,
            }


def weather_observations(counties: list[str], raw_dir: Path = RAW_DIR) -> list[dict]:
    """Every retained daily reading from the counties' stations."""
    rows: dict[tuple, dict] = {}
    for slug in counties:
        for station_id in STATIONS_BY_COUNTY[slug]:
            path = _station_file(raw_dir, slug, station_id)
            if path.exists():
                # Keyed so a reading repeated in a file is kept once (the last one wins).
                rows.update(((r["station_id"], r["date"], r["element"]), r) for r in _read_station(path, station_id))
    return list(rows.values())


def weather_source(count: int, counties: list[str], raw_dir: Path = RAW_DIR) -> dict:
    """The `data_sources` row describing what `weather_observations` read."""
    files = [
        path
        for slug in counties
        for station_id in STATIONS_BY_COUNTY[slug]
        if (path := _station_file(raw_dir, slug, station_id)).exists()
    ]
    return {
        "id": "noaa-ghcn-daily",
        "publisher": PUBLISHER,
        "dataset": "Global Historical Climatology Network Daily (GHCN-Daily)",
        "url": f"{GHCN_BASE}/",
        "retrieved_at": fetched_at(files),
        "record_count": count,
        "notes": (
            f"{len(files)} station files, {GHCN_FIRST_YEAR}-{LAST_YEAR}; elements {', '.join(GHCN_ELEMENTS)}. Readings "
            "with a NOAA quality flag are excluded; values and the remaining flags are kept without unit conversion."
        ),
    }
