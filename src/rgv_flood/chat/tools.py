"""The chatbot's fixed data tools: tested, read-only queries the model calls with values, never SQL.

Each runs through `sqltool.run_bound` (read-only connection, authorizer, time limit, row and cell caps)
with the model's values bound as parameters. Problems come back as `ToolError`, whose message is
safe to show the model.
"""

from __future__ import annotations

import unicodedata

from rgv_flood.chat.sqltool import QueryRefused, run_bound
from rgv_flood.db import Database

COUNTIES = ("cameron", "hidalgo", "starr", "willacy")


class ToolError(QueryRefused):
    """The tool could not answer as asked. The message is safe to show the model."""


def normalize_county(value: str) -> str:
    """'Hidalgo County' -> 'hidalgo'; anything that is not one of the four counties is refused."""
    text = " ".join(str(value or "").lower().split())
    text = text.removesuffix(" county").strip()
    if text not in COUNTIES:
        raise ToolError(f"Unknown county {value!r}. Use one of: {', '.join(COUNTIES)}.")
    return text


def fold(text: str) -> str:
    """Lower-case, accents removed, spaces collapsed: 'Peñitas' and 'PENITAS' fold alike."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).lower().split())


def _places_built(db: Database) -> bool:
    """True when the places tables exist and hold rows. Every pipeline write creates all tables, so a
    database built before build_places.py ran has them empty."""
    tables = run_bound(db, "select count(*) from sqlite_master where type = 'table' "
                           "and name in ('places', 'place_tracts', 'place_aliases')")["rows"][0][0]
    return tables == 3 and run_bound(db, "select exists(select 1 from places)")["rows"][0][0] == 1


def find_place(db: Database, name: str) -> dict:
    """A city, town or census-designated place by name: its county and census tracts.

    Exact name (or alias) matches come first; with none, names starting with the text. More than one
    match is reported as ambiguous with every candidate."""
    if not _places_built(db):
        raise ToolError("Places are not built yet; ask about a county instead.")
    wanted = fold(name)
    if not wanted:
        raise ToolError("Give a place name, e.g. Edinburg.")
    places = run_bound(db, "select place_id, name, full_name, kind, county from places", row_cap=5000)["rows"]
    aliases = dict(run_bound(db, "select alias, place_id from place_aliases", row_cap=5000)["rows"])
    exact = [p for p in places if fold(p[1]) == wanted or aliases.get(wanted) == p[0]]
    chosen = exact or [p for p in places if fold(p[1]).startswith(wanted)]
    matches = []
    for place_id, place_name, full_name, kind, county in sorted(chosen, key=lambda p: p[1]):
        tracts = run_bound(db, "select tract, vintage from place_tracts where place_id = ? order by tract",
                           (place_id,))["rows"]
        matches.append({"place_id": place_id, "name": place_name, "full_name": full_name, "kind": kind,
                        "county": county, "tracts": [t for t, _ in tracts],
                        "tract_vintages": sorted({v for _, v in tracts})})
    result = {"matches": matches, "ambiguous": len(matches) > 1, "from": "places, place_tracts"}
    if not matches:
        result["hint"] = f"No Valley place by that name; ask about a county instead ({', '.join(COUNTIES)})."
    return result
