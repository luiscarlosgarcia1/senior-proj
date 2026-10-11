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

# FEMA publishes a digital flood map (NFHL) for these three. Hidalgo only has the
# 1981 FIRM digitized by its drainage district.
NFHL_COUNTIES: tuple[str, ...] = ("cameron", "starr", "willacy")

# West, south, east, north: a generous box around the four counties, used to
# bound searches. It also covers a strip of Mexico, so it is never the test for
# "inside the study area" (that is each county's boundary polygon).
RGV_BBOX: tuple[float, float, float, float] = (-99.7, 25.6, -96.9, 27.1)

FIPS_TO_SLUG: dict[str, str] = {c["fips"]: slug for slug, c in COUNTIES.items()}
SHORT_NAMES: dict[str, str] = {slug: c["name"].removesuffix(" County") for slug, c in COUNTIES.items()}


def is_county(slug: str) -> bool:
    return slug in COUNTIES
