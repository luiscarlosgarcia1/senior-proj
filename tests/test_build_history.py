"""Pipeline: pipeline/build_history.py — claims, policies, NWS flood reports, gauge years."""

import json
import sqlite3
from contextlib import closing

import build_history
from database import open_database, replace_table


def _report(typetext, county="HIDALGO", **values):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-98.2, 26.2]},
        "properties": {
            "typetext": typetext, "county": county, "valid": "2020-07-26T03:00:00Z", "city": "3 ENE WESLACO",
            "remark": "Streets flooded.", "source": "LAW ENFORCEMENT", "magnitude": "", "lon": -98.2, "lat": 26.2,
            **values,
        },
    }


def test_flood_reports_keep_flood_kinds_in_the_four_counties_once_each():
    features = [
        _report("FLASH FLOOD"),
        _report("FLASH FLOOD"),  # NWS re-issued the same report
        _report("HEAVY RAIN", county="Cameron", magnitude="6.25", valid="2020-07-27T00:00:00Z"),
        _report("HAIL"),  # not flooding
        _report("FLOOD", county="ZAPATA"),  # not one of the four counties
    ]

    rows = build_history.flood_reports(features)

    assert [(r["kind"], r["county"]) for r in rows] == [("flash_flood", "hidalgo"), ("heavy_rain", "cameron")]
    assert rows[0]["city"] == "3 ENE Weslaco"
    assert rows[0]["source"] == "Law Enforcement"
    assert rows[0]["magnitude"] is None  # only heavy rain reports carry an amount
    assert rows[1]["magnitude"] == 6.25


def test_claims_keep_county_year_and_payments(tmp_path):
    claims_file = tmp_path / "claims.ndjson"
    claims_file.write_text("\n".join(json.dumps(c) for c in [
        {"id": "a", "countyCode": "48061", "yearOfLoss": 2008, "dateOfLoss": "2008-07-23T00:00:00.000Z",
         "floodEvent": "Hurricane Dolly", "amountPaidOnBuildingClaim": 1000.5, "amountPaidOnContentsClaim": None,
         "censusGeoid": "480610123051", "latitude": 26.1, "longitude": -97.5},
        {"id": "b", "countyCode": "48201", "yearOfLoss": 2017},  # Harris County: not ours
    ]) + "\n")

    (claim,) = build_history.claims(claims_file)

    assert claim["county"] == "cameron"
    assert (claim["year_of_loss"], claim["date_of_loss"]) == (2008, "2008-07-23")
    assert (claim["paid_building"], claim["paid_contents"], claim["paid_increased_cost_of_compliance"]) == (1000.5, 0.0, 0.0)
    assert claim["census_tract"] == "48061012305"


def test_policies_come_from_the_seed_file(tmp_path):
    (tmp_path / build_history.POLICIES_SEED).write_text("county,year,policies\ncameron,2009,21153\n")

    assert build_history.policies(tmp_path) == [{"county": "cameron", "year": 2009, "policies": 21153}]


def test_gauge_years_are_worked_out_from_the_daily_readings(tmp_path):
    database = tmp_path / "db.sqlite3"
    readings = [
        {"station_id": "S1", "date": f"2020-01-{day:02d}", "element": "PRCP", "value": value,
         "measurement_flag": None, "source_flag": None, "observation_time_flag": None}
        for day, value in ((1, 0), (2, 600), (3, 100))
    ] + [{"station_id": "S1", "date": "2020-01-02", "element": "TMAX", "value": 300,
          "measurement_flag": None, "source_flag": None, "observation_time_flag": None}]
    with open_database(database) as connection:
        replace_table(connection, "weather_observations", readings)
        replace_table(connection, "rainfall_station_years", [])
        connection.execute(build_history.RAINFALL_STATION_YEARS, {"two_inches": build_history.TWO_INCHES_IN_TENTHS_MM})

    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("select * from rainfall_station_years").fetchone()
    # three days reported, 70 mm in all, the wettest 60 mm (over 2 inches, once); the temperature is ignored
    assert row == ("S1", 2020, 3, 700.0, 600.0, 1)
