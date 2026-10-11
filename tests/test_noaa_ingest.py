from __future__ import annotations

import gzip
import json
from pathlib import Path

import noaa_ingest
import pytest
from paths import ghcn_daily_file, storm_events_file

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
    directory.mkdir(parents=True)
    path = directory / f"StormEvents_details-ftp_v1.0_d{year}_c20240101.csv.gz"
    path.write_bytes(gzip.compress("\n".join([STORM_HEADER, *rows]).encode()))


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
    assert noaa_ingest._event_date(date_time, year_month, day) == expected


def test_storm_events_split_by_county_in_one_pass(tmp_path):
    rows = [
        storm_row(EVENT_ID="1"),
        storm_row(EVENT_ID="2", CZ_NAME="CAMERON", EVENT_TYPE="Flood"),
        storm_row(EVENT_ID="3", EVENT_TYPE="Hail"),  # not a flood type
        storm_row(EVENT_ID="4", STATE="OKLAHOMA"),
        storm_row(EVENT_ID="5", BEGIN_LAT="0", BEGIN_LON="0", EVENT_NARRATIVE=""),  # no usable point
    ]
    write_storm_file(tmp_path / "raw", rows)
    data_dir = tmp_path / "data"

    noaa_ingest.ingest_storm_events(tmp_path / "raw", data_dir, ["hidalgo", "cameron"])

    def records(slug):
        path = storm_events_file(slug, data_dir)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    hidalgo, cameron = records("hidalgo"), records("cameron")
    assert [r["record_id"] for r in hidalgo] == ["noaa-storm-events-1", "noaa-storm-events-5"]
    assert [r["record_id"] for r in cameron] == ["noaa-storm-events-2"]

    with_point, without_point = hidalgo
    assert with_point["geometry"] == {"type": "Point", "coordinates": [-98.2, 26.2]}
    assert with_point["summary"] == 'NOAA Storm Events flash flood record near McAllen. Streets "flooded", with water in homes.'
    assert without_point["geometry"] is None
    assert without_point["location_precision"] == "county"
    assert "geometry_absence_reason" in without_point


def test_hand_curated_reports_survive_a_rerun(tmp_path):
    write_storm_file(tmp_path / "raw", [storm_row()])
    data_dir = tmp_path / "data"
    target = storm_events_file("hidalgo", data_dir)
    target.parent.mkdir(parents=True)
    report = {"record_id": "hand-curated-1", "record_kind": "public_report", "event_start": "2018-06-22"}
    stale = {"record_id": "noaa-storm-events-old", "record_kind": "flood_event", "event_start": "2001-01-01"}
    target.write_text("\n".join(json.dumps(r) for r in (report, stale)) + "\n", encoding="utf-8")

    noaa_ingest.ingest_storm_events(tmp_path / "raw", data_dir, ["hidalgo"])

    ids = [json.loads(line)["record_id"] for line in target.read_text(encoding="utf-8").splitlines()]
    assert ids == ["noaa-storm-events-1", "hand-curated-1"]  # sorted by date; stale generated row dropped


def test_ghcn_keeps_clean_rows_in_range_and_drops_flagged_ones(tmp_path):
    station = next(iter(noaa_ingest.STATIONS_BY_COUNTY["hidalgo"]))
    lines = [
        f"{station},20180621,PRCP,1234,,,7,",  # kept
        f"{station},20180621,TMAX,350,,,7,",  # kept, same day
        f"{station},20180622,PRCP,50,,G,7,",  # quality-flagged: dropped
        f"{station},19991231,PRCP,10,,,7,",  # before 2000: dropped
        f"{station},20180623,SNOW,10,,,7,",  # element not retained
    ]
    directory = tmp_path / "raw" / "ghcn-hidalgo"
    directory.mkdir(parents=True)
    (directory / f"{station}.csv.gz").write_bytes(gzip.compress("\n".join(lines).encode()))

    noaa_ingest.ingest_ghcn_daily(tmp_path / "raw", tmp_path / "data", ["hidalgo"])

    path = ghcn_daily_file("hidalgo", tmp_path / "data")
    (record,) = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert record["record_id"] == f"noaa-ghcn-daily-{station.lower()}-2018-06-21"
    observations = record["original_attributes"]["observations"]
    assert observations["PRCP"]["value"] == 1234
    assert observations["PRCP"]["unit"] == "tenths of millimeters"
    assert observations["PRCP"]["source_flag"] == "7"
    assert observations["PRCP"]["quality_flag"] is None
    assert set(observations) == {"PRCP", "TMAX"}
