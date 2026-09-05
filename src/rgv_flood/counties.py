"""The four Lower Rio Grande Valley counties in scope.

FIPS codes are the join key against US Census TIGER boundaries and the county
filter for FEMA NFHL / TWDB source layers.
"""

from __future__ import annotations

COUNTIES: dict[str, dict[str, str]] = {
    "cameron": {"fips": "48061", "name": "Cameron County"},
    "hidalgo": {"fips": "48215", "name": "Hidalgo County"},
    "starr": {"fips": "48427", "name": "Starr County"},
    "willacy": {"fips": "48489", "name": "Willacy County"},
}

FIPS_TO_SLUG: dict[str, str] = {c["fips"]: slug for slug, c in COUNTIES.items()}


def is_county(slug: str) -> bool:
    return slug in COUNTIES
