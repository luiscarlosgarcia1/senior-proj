#!/usr/bin/env python3
"""Load the year-by-year record into the central database: flood-insurance
claims and policies, the flooding people reported to the National Weather
Service, and each rain gauge's yearly totals.

  nfip_claims             every NFIP claim FEMA publishes for the four counties, 1978 on
  nfip_policies_by_year   policies in force per county and year, 2009 on (data/seed/)
  nws_flood_reports       flood, flash flood, heavy rain and coastal flood reports
                          to NWS Brownsville, 2005 on
  rainfall_station_years  per gauge and year: days with a reading, total rain,
                          wettest day, days over 2 inches. Worked out from
                          weather_observations, so build_events.py runs first.
  rainfall_station_months the same per gauge and month, for the trends page

Run:  uv run python pipeline/build_history.py
Safe to re-run (replaces only its own tables).
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

from database import open_database, record_sources, replace_table
from jsonio import read_ndjson
from net import fetched_at
from paths import DATABASE, SEED_DIR
from public_sources import (
    IEM_STORM_REPORTS,
    OPENFEMA,
    STORM_REPORTS_FILE,
    STORM_REPORTS_SINCE,
    nfip_claims,
    nws_storm_reports,
)

from rgv_flood.counties import FIPS_TO_SLUG, SHORT_NAMES

POLICIES_SEED = "nfip-policies-by-year.csv"

# NWS report type -> what this project calls it. Other kinds (hail, wind, ...) are left out.
FLOOD_REPORT_KINDS = {
    "FLASH FLOOD": "flash_flood",
    "FLOOD": "flood",
    "HEAVY RAIN": "heavy_rain",
    "COASTAL FLOOD": "coastal_flood",
}
TWO_INCHES_IN_TENTHS_MM = 508

RAINFALL_STATION_YEARS = """
INSERT INTO rainfall_station_years
SELECT station_id,
       CAST(substr(date, 1, 4) AS INTEGER),
       count(*),
       sum(value),
       max(value),
       sum(value >= :two_inches)
FROM weather_observations
WHERE element = 'PRCP'
GROUP BY station_id, substr(date, 1, 4)
"""

RAINFALL_STATION_MONTHS = """
INSERT INTO rainfall_station_months
SELECT station_id,
       CAST(substr(date, 1, 4) AS INTEGER),
       CAST(substr(date, 6, 2) AS INTEGER),
       count(*),
       sum(value),
       max(value)
FROM weather_observations
WHERE element = 'PRCP'
GROUP BY station_id, substr(date, 1, 4), substr(date, 6, 2)
"""


# Compass directions in NWS place names ("7 ENE Brownsville") stay capitalized.
COMPASS_POINT = re.compile(r"\b(?:[NSEW]|NE|NW|SE|SW|NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW)\b", re.IGNORECASE)


def _place(city: object) -> str | None:
    if not isinstance(city, str) or not city.strip():
        return None
    return COMPASS_POINT.sub(lambda match: match.group(0).upper(), city.strip().title())


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def flood_reports(features: list[dict]) -> list[dict]:
    """The storm reports about flooding in the four counties, one row each.

    A report NWS re-issued (to correct it, say) appears twice in the archive
    with the same time, place, kind and remark; it is kept once.
    """
    slug_by_name = {name.upper(): slug for slug, name in SHORT_NAMES.items()}
    rows: dict[str, dict] = {}
    for feature in features:
        p = feature["properties"]
        kind = FLOOD_REPORT_KINDS.get((p.get("typetext") or "").upper())
        county = slug_by_name.get((p.get("county") or "").upper())
        if not kind or not county:
            continue
        identity = "|".join(str(p.get(key)) for key in ("valid", "lon", "lat", "typetext", "remark"))
        report_id = hashlib.sha1(identity.encode()).hexdigest()[:16]
        rows[report_id] = {
            "id": report_id,
            "county": county,
            "kind": kind,
            "reported_at": p["valid"],
            "city": _place(p.get("city")),
            "remark": (p.get("remark") or "").strip() or None,
            "source": (p.get("source") or "").title() or None,
            "magnitude": _number(p.get("magnitude")) if kind == "heavy_rain" else None,
            "lon": _number(p.get("lon")),
            "lat": _number(p.get("lat")),
        }
    return sorted(rows.values(), key=lambda row: (row["reported_at"], row["id"]))


def claims(path: Path) -> list[dict]:
    """One row per NFIP claim, keeping the fields the analysis and map use."""
    rows = []
    for c in read_ndjson(path):
        county = FIPS_TO_SLUG.get(c.get("countyCode"))
        if not county or not c.get("yearOfLoss"):
            continue
        rows.append({
            "id": c["id"],
            "county": county,
            "date_of_loss": (c.get("dateOfLoss") or "")[:10] or None,
            "year_of_loss": int(c["yearOfLoss"]),
            "flood_event": c.get("floodEvent"),
            "cause_of_damage": c.get("causeOfDamage"),
            "paid_building": c.get("amountPaidOnBuildingClaim") or 0.0,
            "paid_contents": c.get("amountPaidOnContentsClaim") or 0.0,
            "paid_increased_cost_of_compliance": c.get("amountPaidOnIncreasedCostOfComplianceClaim") or 0.0,
            "building_damage": c.get("buildingDamageAmount"),
            "contents_damage": c.get("contentsDamageAmount"),
            "rated_flood_zone": c.get("ratedFloodZone"),
            "occupancy_type": c.get("occupancyType"),
            "census_tract": (c.get("censusGeoid") or "")[:11] or None,
            "lon": c.get("longitude"),
            "lat": c.get("latitude"),
        })
    return rows


def policies(seed_dir: Path) -> list[dict]:
    """Policies in force per county and year, from the seed file."""
    with (seed_dir / POLICIES_SEED).open(encoding="utf-8", newline="") as seed:
        return [
            {"county": row["county"], "year": int(row["year"]), "policies": int(row["policies"])}
            for row in csv.DictReader(seed)
        ]


def _sources(reports_file: Path, reports: list[dict], claims_file: Path, claim_rows: list[dict]) -> list[dict]:
    return [
        {
            "id": "nws-local-storm-reports",
            "publisher": "National Weather Service, Brownsville (archive kept by Iowa Environmental Mesonet)",
            "dataset": "Local Storm Reports: flooding",
            "url": IEM_STORM_REPORTS,
            "retrieved_at": fetched_at([reports_file]),
            "record_count": len(reports),
            "notes": f"Flood, flash flood, heavy rain and coastal flood reports since {STORM_REPORTS_SINCE[:4]}, "
                     "as reported to NWS by the public, police, emergency managers and spotters.",
        },
        {
            "id": "fema-nfip-claims",
            "publisher": "FEMA (OpenFEMA)",
            "dataset": "NFIP redacted claims",
            "url": f"{OPENFEMA}/v3/NfipClaims",
            "retrieved_at": fetched_at([claims_file]),
            "record_count": len(claim_rows),
            "notes": "Every claim with a loss in the four counties, 1978 on. Locations are rounded by FEMA.",
        },
        {
            "id": "fema-nfip-policies",
            "publisher": "FEMA (OpenFEMA)",
            "dataset": "NFIP redacted policies (v2), counted by county and year",
            "url": f"{OPENFEMA}/v2/FimaNfipPolicies",
            "retrieved_at": None,
            "record_count": None,
            "notes": f"Kept in data/seed/{POLICIES_SEED}: FEMA retired this dataset on 2026-10-15.",
        },
    ]


def main(database: Path = DATABASE, seed_dir: Path = SEED_DIR) -> None:
    reports = flood_reports(nws_storm_reports())
    claims_file = nfip_claims()
    claim_rows = claims(claims_file)
    policy_rows = policies(seed_dir)

    with open_database(database) as connection:
        replace_table(connection, "nws_flood_reports", reports)
        replace_table(connection, "nfip_claims", claim_rows)
        replace_table(connection, "nfip_policies_by_year", policy_rows)
        replace_table(connection, "rainfall_station_years", [])
        connection.execute(RAINFALL_STATION_YEARS, {"two_inches": TWO_INCHES_IN_TENTHS_MM})
        station_years = connection.execute("select count(*) from rainfall_station_years").fetchone()[0]
        replace_table(connection, "rainfall_station_months", [])
        connection.execute(RAINFALL_STATION_MONTHS)
        station_months = connection.execute("select count(*) from rainfall_station_months").fetchone()[0]
        record_sources(connection, _sources(STORM_REPORTS_FILE, reports, claims_file, claim_rows))

    print(f"nws_flood_reports: {len(reports)} reports")
    print(f"nfip_claims: {len(claim_rows):,} claims; nfip_policies_by_year: {len(policy_rows)} county-years")
    print(f"rainfall_station_years: {station_years} gauge-years; rainfall_station_months: {station_months} gauge-months")
    print("written to", database)


if __name__ == "__main__":
    main()
