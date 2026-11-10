"""Decide whether a news story is about water in one of the four counties, and
pull out the places it names.

Pure functions, no network. "About water" is wide on purpose: floods, rain,
storms and hurricanes, drought and water supply, drainage and water systems, and
anything else that says "water". Each story gets the topics it matched so a
reader can narrow it again. A story is kept only if it also names a place in
the Valley (a town, a county, or the Valley as a whole).

`match_story` is the authority. `mentions_flood` on the headline `headline_from_slug`
rebuilds from an address is a cheap pre-filter, so pages that cannot match are never
downloaded; that rebuilt headline also stands in for sites whose pages we may not read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# What each topic is, as word-bounded patterns (English and Spanish). Order matters only for the
# order topics are reported in. "water" on its own is the weakest signal and is kept as its own topic.
TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    topic: re.compile(pattern, re.IGNORECASE)
    for topic, pattern in {
        "flood": r"\b(?:flood\w*|inundaci\w+|high[- ]water|standing water|ponding|swift[- ]water|water rescues?"
                 r"|low[- ]water crossings?|washouts?|washed[- ]out roads?)\b",
        "rain": r"\b(?:rain(?:s|ed|ing|fall|storms?|y|drops?|water)?|downpours?|deluge|torrential|thunderstorms?"
                r"|lluvias?|precipitation)\b",
        "storm": r"\b(?:hurricanes?|tropical (?:storms?|depressions?|waves?|cyclones?)|storm surge|storms?|huracanes?"
                 r"|huracán|tormentas?|cyclones?)\b",
        "drought": r"\b(?:drought\w*|dry spell|water (?:shortages?|restrictions?|rationing|conservation|supply|supplies|crisis"
                   r"|levels?)|lake levels?|falcon (?:lake|dam|reservoir)|amistad|reservoirs?|sequ[íi]a|escasez de agua)\b",
        "water_system": r"\b(?:drainage|drains?|ditch(?:es)?|levees?|resacas?|irrigation|canals?|pump stations?|sewers?"
                        r"|sewage|wastewater|stormwater|water mains?|boil[- ]water|water (?:treatment|quality|plants?|lines?"
                        r"|districts?|utilit(?:y|ies)|systems?|towers?|boards?|bills?|rates?|pipes?|pressure|outage)"
                        r"|waterways?|aqueducts?|drenaje|riego|alcantarillad\w+|sea level"
                        r"|coastal erosion|tidal|dams?)\b",
        "water": r"\b(?:water|waters|agua)\b",
    }.items()
}

# The river's name inside a place name ("Rio Grande Valley", "Rio Grande City") says nothing about water, so it is not a
# water word. `news_clean` also drops these from rows an earlier build stored.
PLACE_NAME_TERMS = frozenset(("rio grande", "rio bravo"))

# City or town -> county slug. Case-sensitive in the text, so "mission" the word is not Mission the city.
CITY_COUNTY: dict[str, str] = {
    **dict.fromkeys(
        ("McAllen", "Edinburg", "Mission", "Pharr", "Weslaco", "Donna", "Alamo", "San Juan", "Mercedes", "Elsa", "Edcouch",
         "La Joya", "Palmview", "Progreso", "Hargill", "Peñitas", "Penitas", "Palmhurst", "Sharyland", "La Villa", "Alton",
         "Faysville", "Granjeno", "Monte Alto", "Linn", "San Carlos", "McCook", "Sullivan City", "Lopezville", "Scissors",
         "Delta Lake", "Citrus City", "Doolittle", "Edinburg"),
        "hidalgo",
    ),
    **dict.fromkeys(
        ("Brownsville", "Harlingen", "San Benito", "Port Isabel", "South Padre Island", "Los Fresnos", "La Feria",
         "Santa Rosa", "Rio Hondo", "Laguna Vista", "Primera", "Palm Valley", "Boca Chica", "Olmito", "Rangerville",
         "Bluetown", "Combes", "Lozano", "Arroyo City", "Rancho Viejo", "Laguna Heights", "Los Indios", "Indian Lake",
         "Santa Maria", "Cameron Park", "Bayview", "Laureles", "Villa Pancho"),
        "cameron",
    ),
    **dict.fromkeys(("Rio Grande City", "Roma", "La Grulla", "Escobares", "Garciasville", "Los Saenz", "Fronton", "Salineno"), "starr"),
    **dict.fromkeys(("Raymondville", "Lyford", "Sebastian", "Port Mansfield", "San Perlita", "Lasara", "Willamar"), "willacy"),
}
# Names that are also ordinary capitalized words: only counted when they are not the first word of a
# sentence ("Mission statement ..."), and not trusted from an address alone.
AMBIGUOUS_CITIES = frozenset(("Mission", "Alamo", "Donna", "Roma", "Sebastian", "Primera", "Elsa", "Linn", "Alton", "Scissors",
                              "Progreso", "Combes", "Laureles", "Bayview", "Doolittle"))

COUNTY_NAME = re.compile(
    r"\b(Cameron|Hidalgo|Starr|Willacy)\s+Count(?:y|ies)\b|\bCondado de (Cameron|Hidalgo|Starr|Willacy)\b", re.IGNORECASE
)
REGION = re.compile(r"\b(?:Lower )?Rio Grande Valley\b|\bRGV\b|\b[Tt]he Valley\b")
_CITY = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITY_COUNTY), key=len, reverse=True)) + r")\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)$")


@dataclass(frozen=True)
class StoryMatch:
    counties: tuple[str, ...]  # in order of first mention; empty when only the Valley as a whole is named
    city: str | None  # the first city named
    terms: tuple[str, ...]  # the water words found, lower-case, in order of appearance
    topics: tuple[str, ...] = ()  # flood, rain, storm, drought, water_system, water


def topics_in(text: str) -> list[tuple[int, str, str]]:
    """(position, matched word, topic) for every water word in `text`, in order of appearance."""
    found = [
        (hit.start(), hit.group(0).lower(), topic)
        for topic, pattern in TOPIC_PATTERNS.items()
        for hit in pattern.finditer(text)
    ]
    return sorted(found)


def mentions_flood(text: str) -> bool:
    """Whether `text` has any water word (the name is from when floods were all it looked for)."""
    return any(pattern.search(text) for pattern in TOPIC_PATTERNS.values())


def _mentions(text: str, offset: int) -> list[tuple[int, str | None, str | None, bool]]:
    """(position, county slug, city, names the whole Valley) for every place named in `text`."""
    found: list[tuple[int, str | None, str | None, bool]] = []
    for hit in COUNTY_NAME.finditer(text):
        found.append((offset + hit.start(), (hit.group(1) or hit.group(2)).lower(), None, False))
    for hit in _CITY.finditer(text):
        name = hit.group(1)
        if name in AMBIGUOUS_CITIES and _SENTENCE_START.search(text[: hit.start()]):
            continue
        found.append((offset + hit.start(), CITY_COUNTY[name], name, False))
    for hit in REGION.finditer(text):
        found.append((offset + hit.start(), None, None, True))
    return found


def has_valley_place(text: str, *, strict: bool = False) -> bool:
    """Whether `text` names a Valley place. `strict` ignores names that are also common words (Mission,
    Alamo, Roma ...), for text we cannot read in full, such as an address."""
    for _, _, city, _ in _mentions(text, 0):
        if not (strict and city in AMBIGUOUS_CITIES):
            return True
    return False


def match_story(headline: str, description: str) -> StoryMatch | None:
    """The story's counties, first city, water words and topics; None unless it has a water word and a place."""
    words = topics_in(f"{headline} {description}")
    if not words:
        return None
    # The description is offset far past the headline so headline mentions sort first.
    mentions = sorted(_mentions(headline, 0) + _mentions(description, 1_000_000), key=lambda m: m[0])
    if not mentions:
        return None
    return StoryMatch(
        counties=tuple(dict.fromkeys(county for _, county, _, _ in mentions if county)),
        city=next((city for _, _, city, _ in mentions if city), None),
        terms=tuple(dict.fromkeys(term for _, term, _ in words)),
        topics=tuple(dict.fromkeys(topic for _, _, topic in words)),
    )


# ---- an address stands in for a headline ----

_CANONICAL = {name.lower(): name for name in CITY_COUNTY} | {"rgv": "RGV"}
_CANONICAL_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _CANONICAL), key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _slug(url: str) -> str:
    path = urlparse(url).path if "://" in url else url
    segments = [part for part in path.split("/") if part]
    slug = segments[-1] if segments else ""
    slug = re.sub(r"\.(?:html?|php|aspx?)$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[,_]\d+$", "", slug)  # "peterson-visits-rgv,6491"
    return re.sub(r"-\d{5,}$", "", slug)  # a trailing story number


def headline_from_slug(url: str) -> str:
    """A readable headline from the last part of an address: words capitalized, Valley place names spelled right."""
    words = [word for word in re.split(r"[-_+]", _slug(url)) if word]
    text = " ".join(word.capitalize() for word in words)
    return _CANONICAL_RE.sub(lambda hit: _CANONICAL[hit.group(1).lower()], text)



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
