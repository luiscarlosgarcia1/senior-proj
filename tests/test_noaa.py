from __future__ import annotations

import gzip
from pathlib import Path

import noaa
import pytest

STORM_HEADER = (
    "STATE,CZ_NAME,EVENT_TYPE,BEGIN_LAT,BEGIN_LON,BEGIN_DATE_TIME,BEGIN_YEARMONTH,BEGIN_DAY,"
    "END_DATE_TIME,END_YEARMONTH,END_DAY,EVENT_ID,BEGIN_LOCATION,EVENT_NARRATIVE,EPISODE_NARRATIVE"
)


def storm_row(**overrides: str) -> str:
    row = {
        "STATE": "TEXAS", "CZ_NAME": "HIDALGO", "EVENT_TYPE": "Flash Flood",
        "BEGIN_LAT": "26.2", "BEGIN_LON": "-98.2", "BEGIN_DATE_TIME": "21-JUN-18 17:00:00",
        "BEGIN_YEARMONTH": "201806", "BEGIN_DAY": "21", "END_DATE_TIME": "22-JUN-18 03:00:00",
        "END_YEARMONTH": "201806", "END_DAY": "22", "EVENT_ID": "1", "BEGIN_LOCATION": "McAllen",
        "EVENT_NARRATIVE": 'Streets "flooded", with water in homes.', "EPISODE_NARRATIVE": "",
    } | overrides
    return ",".join('"' + value.replace('"', '""') + '"' for value in row.values())


def write_storm_file(raw_dir: Path, rows: list[str], year: int = 2018) -> None:
    directory = raw_dir / "storm-events"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"StormEvents_details-ftp_v1.0_d{year}_c20240101.csv.gz"
    path.write_bytes(gzip.compress("\n".join([STORM_HEADER, *rows]).encode()))


def write_station_file(raw_dir: Path, slug: str, station_id: str, lines: list[str]) -> None:
    directory = raw_dir / f"ghcn-{slug}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{station_id}.csv.gz").write_bytes(gzip.compress("\n".join(lines).encode()))


@pytest.mark.parametrize(
    ("date_time", "year_month", "day", "expected"),
    [
        ("21-JUN-18 17:00:00", "", "", "2018-06-21"),
        ("5-JAN-99 00:00:00", "", "", "1999-01-05"),
        ("", "201806", "7", "2018-06-07"),  # falls back to YEARMONTH (YYYYMM) + DAY
        ("not a date", "", "", None),
        ("21-XXX-18 00:00:00", "", "", None),
    ],
)
def test_event_date(date_time, year_month, day, expected):
    assert noaa._event_date(date_time, year_month, day) == expected


def test_storm_events_keeps_flood_types_for_the_wanted_counties(tmp_path):
    write_storm_file(tmp_path, [
        storm_row(EVENT_ID="1"),
        storm_row(EVENT_ID="2", CZ_NAME="CAMERON", EVENT_TYPE="Flood"),
        storm_row(EVENT_ID="3", EVENT_TYPE="Hail"),  # not a flood type
        storm_row(EVENT_ID="4", STATE="OKLAHOMA"),
        storm_row(EVENT_ID="5", CZ_NAME="STARR"),  # a county that wasn't asked for
    ])

    events = noaa.storm_events(["hidalgo", "cameron"], tmp_path)

    assert [(e["id"], e["county"], e["type"]) for e in events] == [
        ("noaa-storm-events-1", "hidalgo", "Flash flood"),
        ("noaa-storm-events-2", "cameron", "Flood"),
    ]


def test_storm_event_row_keeps_what_noaa_published(tmp_path):
    write_storm_file(tmp_path, [storm_row()])

    (event,) = noaa.storm_events(["hidalgo"], tmp_path)

    assert event == {
        "id": "noaa-storm-events-1",
        "county": "hidalgo",
        "date": "2018-06-21",
        "date_end": "2018-06-22",
        "type": "Flash flood",
        "location": "McAllen, Hidalgo County, Texas",
        "precision": "exact",
        "summary": 'NOAA Storm Events flash flood record near McAllen. Streets "flooded", with water in homes.',
        "narrative": 'Streets "flooded", with water in homes.',
        "source_url": f"{noaa.STORM_EVENTS_BASE}/StormEvents_details-ftp_v1.0_d2018_c20240101.csv.gz",
        "source_lon": -98.2,
        "source_lat": 26.2,
    }


def test_storm_event_without_a_usable_point_is_located_by_county(tmp_path):
    write_storm_file(tmp_path, [storm_row(BEGIN_LAT="0", BEGIN_LON="0", BEGIN_LOCATION="", EVENT_NARRATIVE="")])

    (event,) = noaa.storm_events(["hidalgo"], tmp_path)

    assert (event["source_lon"], event["source_lat"], event["precision"]) == (None, None, "county")
    assert event["location"] == "Hidalgo County, Texas"
    assert event["summary"] == "NOAA Storm Events flash flood record in Hidalgo County."
    assert event["narrative"] == "NOAA Storm Events event ID 1 (Flash Flood; 2018)."


def test_weather_observations_keep_clean_readings_in_range(tmp_path):
    station = next(iter(noaa.STATIONS_BY_COUNTY["hidalgo"]))
    write_station_file(tmp_path, "hidalgo", station, [
        f"{station},20180621,PRCP,1234,,,7,",  # kept
        f"{station},20180621,TMAX,350,,,7,0700",  # kept, same day
        f"{station},20180622,PRCP,50,,G,7,",  # quality-flagged: dropped
        f"{station},19991231,PRCP,10,,,7,",  # before 2000: dropped
        f"{station},20180623,SNOW,10,,,7,",  # element not retained
    ])

    readings = noaa.weather_observations(["hidalgo"], tmp_path)

    assert readings == [
        {
            "station_id": station, "date": "2018-06-21", "element": "PRCP", "value": 1234,
            "measurement_flag": None, "source_flag": "7", "observation_time_flag": None,
        },
        {
            "station_id": station, "date": "2018-06-21", "element": "TMAX", "value": 350,
            "measurement_flag": None, "source_flag": "7", "observation_time_flag": "0700",
        },
    ]


def test_weather_stations_lists_every_station_of_the_counties():
    stations = noaa.weather_stations(["hidalgo", "willacy"])

    assert len(stations) == len(noaa.STATIONS_BY_COUNTY["hidalgo"]) + len(noaa.STATIONS_BY_COUNTY["willacy"])
    assert {s["county"] for s in stations} == {"hidalgo", "willacy"}
    first = stations[0]
    assert first["source_url"] == f"{noaa.GHCN_BASE}/{first['station_id']}.csv.gz"


def test_download_skips_the_listing_when_every_year_is_cached(tmp_path, monkeypatch):
    for year in range(noaa.FIRST_YEAR, noaa.LAST_YEAR + 1):
        write_storm_file(tmp_path, [], year=year)
    monkeypatch.setattr(noaa, "get_text", lambda url: pytest.fail("NOAA's listing should not be fetched"))
    monkeypatch.setattr(noaa, "download", lambda url, dest: pytest.fail("nothing should be downloaded"))

    noaa.download_raw_files([], tmp_path)
