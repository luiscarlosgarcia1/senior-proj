"""Documented relative-severity mapping.

The application never computes a single "official" flood score. This table is the
*only* place source categories are translated into a shared display class, and it
translates *only* categories that can be responsibly compared. Anything not listed
here must render under its own original label and stay out of the relative legend.

Each entry records: source dataset, the original category value, the assigned
relative class, and a short rationale. Keep this in sync with the data dictionary.
"""

from __future__ import annotations

from typing import Literal

RelativeClass = Literal["high", "moderate", "low", "uncategorized"]

# Ordered worst-to-best for legend rendering.
RELATIVE_CLASSES: tuple[RelativeClass, ...] = ("high", "moderate", "low", "uncategorized")

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
