"""Documented relative-severity mapping.

The application never computes a single "official" flood score. This module is the
*only* place source categories are translated into a shared display class, and it
translates *only* categories that can be responsibly compared. Anything it cannot
place lands in ``uncategorized`` and renders under its own original label.

Two entry points:

- ``MAPPING`` / ``relative_class_for`` — an explicit table for named categories
  (used for the TWDB modeled-frequency layers). Each row records source, original
  category, assigned class, and a rationale; keep it in sync with the data dictionary.
- ``classify_fema_zone`` — the rule set for FEMA-style zone letters. Applies to the
  FEMA NFHL and to Hidalgo's digitized 1981 FIRM, which uses the same lettering
  (legacy Zone B == shaded Zone X, legacy Zone C == Zone X). The layer's ``source``
  and ``vintage`` are always carried alongside so a 1981 zone is never shown as if
  it were current effective data.
"""

from __future__ import annotations

import re
from typing import Literal

RelativeClass = Literal["high", "moderate", "low", "uncategorized"]

# Ordered worst-to-best for legend rendering.
RELATIVE_CLASSES: tuple[RelativeClass, ...] = ("high", "moderate", "low", "uncategorized")

_NUMBERED_A_ZONE = re.compile(r"^A\d+$")  # A1..A30 — legacy numbered SFHA zones
_NUMBERED_V_ZONE = re.compile(r"^V\d+$")  # V1..V30 — legacy numbered coastal SFHA zones


def _clean(value: object) -> str:
    """Normalize a possibly-null / non-string cell to an upper-case token."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("", "nan", "none", "<na>", "null"):
        return ""
    return text.upper()


def classify_fema_zone(fld_zone: str | None, zone_subty: str | None = None) -> RelativeClass:
    """Map a FEMA flood-zone letter (+ optional subtype) to a relative class.

    high      — 1% annual-chance Special Flood Hazard Area (A/AE/AH/AO/A##, V/VE/V##,
                and the floodway within it)
    moderate  — 0.2% annual-chance hazard (Zone X shaded, legacy Zone B)
    low       — minimal hazard (Zone X unshaded, legacy Zone C)
    uncategorized — open water, "area not included", blank, or anything unrecognized
    """
    zone = _clean(fld_zone)
    subty = _clean(zone_subty)

    if zone in ("", "OPEN WATER", "AREA NOT INCLUDED", "D", "NONE"):
        return "uncategorized"
    if zone in ("V", "VE") or _NUMBERED_V_ZONE.match(zone):
        return "high"
    if zone in ("A", "AE", "AH", "AO", "AR", "A99") or _NUMBERED_A_ZONE.match(zone):
        return "high"
    if zone == "B":
        return "moderate"
    if zone == "X" and "0.2" in subty:
        return "moderate"
    if zone in ("X", "C"):
        return "low"
    return "uncategorized"

MAPPING: list[dict[str, str]] = [
    {
        "source": "FEMA NFHL",
        "original_category": "AE",
        "relative_class": "high",
        "rationale": "1% annual-chance floodplain with base flood elevations (SFHA).",
    },
    {
        "source": "FEMA NFHL",
        "original_category": "A",
        "relative_class": "high",
        "rationale": "1% annual-chance floodplain, no base flood elevation (SFHA).",
    },
    {
        "source": "FEMA NFHL",
        "original_category": "AO",
        "relative_class": "high",
        "rationale": "1% annual-chance shallow flooding / sheet flow (SFHA).",
    },
    {
        "source": "FEMA NFHL",
        "original_category": "VE",
        "relative_class": "high",
        "rationale": "1% annual-chance coastal floodplain with wave action (SFHA).",
    },
    {
        "source": "FEMA NFHL",
        "original_category": "X (0.2% annual chance)",
        "relative_class": "moderate",
        "rationale": "0.2% annual-chance flood hazard area.",
    },
    {
        "source": "FEMA NFHL",
        "original_category": "X",
        "relative_class": "low",
        "rationale": "Area of minimal flood hazard outside the 0.2% annual chance.",
    },
    {
        "source": "TWDB 2025 cursory floodplain",
        "original_category": "1% annual chance",
        "relative_class": "high",
        "rationale": "Modeled 1% annual-chance extent; contextual, not regulatory.",
    },
    {
        "source": "TWDB 2025 cursory floodplain",
        "original_category": "0.2% annual chance",
        "relative_class": "moderate",
        "rationale": "Modeled 0.2% annual-chance extent; contextual, not regulatory.",
    },
    {
        "source": "Hidalgo County DD No. 1 digitized 1981 map",
        "original_category": "Flood zone",
        "relative_class": "uncategorized",
        "rationale": (
            "Historic (1981) local reference. Zone semantics are not confirmed "
            "equivalent to current FEMA classes; shown under its own label only."
        ),
    },
]


def relative_class_for(source: str, original_category: str) -> RelativeClass:
    for entry in MAPPING:
        if entry["source"] == source and entry["original_category"] == original_category:
            return entry["relative_class"]  # type: ignore[return-value]
    return "uncategorized"
