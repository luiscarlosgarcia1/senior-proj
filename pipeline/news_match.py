"""Decide whether a news story is about flooding in one of the four counties, and
pull out the places it names.

Pure functions, no network. A story is kept only when it has both a flood term
and a place that resolves to a county; `match_story` is the authority and
`slug_may_be_flood` is a cheap pre-filter on a URL so pages that cannot match
are never downloaded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Stems: "flood" also finds "flooding", "floods" and "flooded". The Spanish
# terms are an addition beyond the design (KRGV publishes some stories in
# Spanish); "inundaci" covers "inundación" and "inundaciones".
FLOOD_TERMS: tuple[str, ...] = (
    "flash flood", "street flooding", "flood", "drainage", "heavy rain", "rainfall",
    "storm surge", "hurricane", "tropical storm",
    "inundaci", "lluvia", "tormenta",
)

# City or town -> county slug. Case-sensitive in the text, so "mission" the word
# is not Mission the city.
CITY_COUNTY: dict[str, str] = {
    **dict.fromkeys(
        ("McAllen", "Edinburg", "Mission", "Pharr", "Weslaco", "Donna", "Alamo", "San Juan", "Mercedes",
         "Elsa", "Edcouch", "La Joya", "Palmview", "Progreso", "Hargill"),
        "hidalgo",
    ),
    **dict.fromkeys(
        ("Brownsville", "Harlingen", "San Benito", "Port Isabel", "South Padre Island", "Los Fresnos",
         "La Feria", "Santa Rosa", "Rio Hondo", "Laguna Vista", "Primera"),
        "cameron",
    ),
    **dict.fromkeys(("Rio Grande City", "Roma", "La Grulla", "Escobares"), "starr"),
    **dict.fromkeys(("Raymondville", "Lyford", "Sebastian", "Port Mansfield", "San Perlita"), "willacy"),
}
# Names that are also ordinary capitalized words: only counted when they are not
# the first word of a sentence ("Mission statement ...").
AMBIGUOUS_CITIES = frozenset(("Mission", "Alamo", "Donna", "Roma", "Sebastian", "Primera", "Elsa"))

COUNTY_NAME = re.compile(r"\b(Cameron|Hidalgo|Starr|Willacy)\s+Count(?:y|ies)\b", re.IGNORECASE)
_CITY = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITY_COUNTY), key=len, reverse=True)) + r")\b")
_TERM = re.compile(r"\b(" + "|".join(re.escape(t) for t in FLOOD_TERMS) + r")\w*", re.IGNORECASE)
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)$")


@dataclass(frozen=True)
class StoryMatch:
    counties: tuple[str, ...]  # in order of first mention
    city: str | None  # the first city named
    terms: tuple[str, ...]  # the flood terms found, lower-case


def _mentions(text: str, offset: int) -> list[tuple[int, str, str | None]]:
    """(position, county slug, city or None) for every place named in `text`."""
    found = []
    for hit in COUNTY_NAME.finditer(text):
        found.append((offset + hit.start(), hit.group(1).lower(), None))
    for hit in _CITY.finditer(text):
        name = hit.group(1)
        if name in AMBIGUOUS_CITIES and _SENTENCE_START.search(text[: hit.start()]):
            continue
        found.append((offset + hit.start(), CITY_COUNTY[name], name))
    return found


def match_story(headline: str, description: str) -> StoryMatch | None:
    """The story's counties, first city and flood terms; None unless it has a
    flood term and a place."""
    terms = tuple(dict.fromkeys(hit.group(1).lower() for hit in _TERM.finditer(f"{headline} {description}")))
    if not terms:
        return None
    # The description is offset far past the headline so headline mentions sort first.
    mentions = sorted(_mentions(headline, 0) + _mentions(description, 1_000_000))
    if not mentions:
        return None
    counties = tuple(dict.fromkeys(county for _, county, _ in mentions))
    city = next((name for _, _, name in mentions if name), None)
    return StoryMatch(counties=counties, city=city, terms=terms)


def slug_may_be_flood(url: str) -> bool:
    """Whether the last part of the URL (a headline, hyphenated) has a flood term."""
    segments = [part for part in urlparse(url).path.split("/") if part]
    slug = segments[-1].rsplit(".", 1)[0].replace("-", " ") if segments else ""
    return _TERM.search(slug) is not None


_STREET = re.compile(
    r"\b(?:[A-Z][\w.']*\s+){1,3}(?:Road|Rd|Street|St|Avenue|Ave|Boulevard|Blvd|Highway|Drive|Dr|Lane|Ln"
    r"|Canal|Resaca|Drain|Bridge|Expressway|Parkway|Freeway)\b"
)
_ROUTE = re.compile(r"\b(?:Expressway|Highway|Interstate|FM|US|State Highway|Loop|Business)\s+\d+\b")


def places_in(text: str) -> str | None:
    """Streets, roads, routes and waterways the text names, joined by '; ', or None."""
    hits = sorted(
        [(m.start(), m.group(0)) for m in _STREET.finditer(text)]
        + [(m.start(), m.group(0)) for m in _ROUTE.finditer(text)]
    )
    names = list(dict.fromkeys(name for _, name in hits))
    return "; ".join(names) if names else None
