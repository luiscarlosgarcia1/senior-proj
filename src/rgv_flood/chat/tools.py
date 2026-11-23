"""The chatbot's fixed data tools: tested, read-only queries the model calls with values, never SQL.

Each runs through `sqltool.run_bound` (read-only connection, authorizer, time limit, row and cell caps)
with the model's values bound as parameters. Problems come back as `ToolError`, whose message is
safe to show the model.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

from rgv_flood.chat.sqltool import QueryRefused, run_bound
from rgv_flood.data_access import COMPLETE_GAUGE_DAYS
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


# ---- year ranges ---------------------------------------------------------------------------------

DEFAULT_YEARS = 10  # with no years given, the last ten full years in the data


def year_range(db: Database, table: str, column: str, year_from: int | None, year_to: int | None) -> tuple[int, int]:
    """The years to report: the request clipped to what `table` holds, or by default its last ten full
    years. Reversed bounds are swapped; a request entirely outside the data is refused with the range."""
    lo, hi = run_bound(db, f"select min({column}), max({column}) from {table}")["rows"][0]
    if lo is None:
        raise ToolError(f"{table} has no rows.")
    lo, hi = int(lo), int(hi)
    if year_from is None and year_to is None:
        this_year = datetime.now(ZoneInfo("America/Chicago")).year  # the Valley's calendar
        last = hi - 1 if hi >= this_year and hi > lo else hi
        return max(lo, last - DEFAULT_YEARS + 1), last
    start = int(year_from if year_from is not None else lo)
    end = int(year_to if year_to is not None else hi)
    if start > end:
        start, end = end, start
    if end < lo or start > hi:
        raise ToolError(f"{table} covers {lo}–{hi}; ask within that.")
    return max(start, lo), min(end, hi)


def _one_place(db: Database, place: str) -> dict:
    found = find_place(db, place)
    if not found["matches"]:
        raise ToolError(found["hint"])
    if found["ambiguous"]:
        names = ", ".join(f"{m['name']} ({m['county']})" for m in found["matches"])
        raise ToolError(f"{place!r} matches several places: {names}. Use the exact name.")
    return found["matches"][0]


def _county_or_place(county: str | None, place: str | None) -> str | None:
    """The normalized county, or None when the question is about a place; exactly one must be given."""
    if (county is None) == (place is None):
        raise ToolError("Give a county or a place, not both and not neither.")
    return normalize_county(county) if county is not None else None


# ---- claims --------------------------------------------------------------------------------------


def claims_summary(db: Database, *, county: str | None = None, place: str | None = None,
                   year_from: int | None = None, year_to: int | None = None) -> dict:
    """NFIP claims and dollars paid (building + contents + increased cost of compliance) per year, for a
    county or for the census tracts making up a place. Claims per 1,000 policies only at county level, and
    only where policy counts exist."""
    county_name = _county_or_place(county, place)
    first, last = year_range(db, "nfip_claims", "year_of_loss", year_from, year_to)
    if place is not None:
        match = _one_place(db, place)
        if not match["tracts"]:
            raise ToolError(f"No census tracts are linked to {match['name']}; ask about {match['county']} county.")
        where = f"census_tract in ({','.join('?' * len(match['tracts']))})"
        params: tuple = (*match["tracts"],)
        scope, who = f"tracts of {match['name']}", f"{match['name']} ({match['county']} county, by census tract)"
    else:
        where, params, scope, who = "county = ?", (county_name,), "county", f"{county_name} county"
    paid = "paid_building + paid_contents + paid_increased_cost_of_compliance"
    found = {y: (n, p) for y, n, p in run_bound(
        db, f"select year_of_loss, count(*), sum({paid}) from nfip_claims where {where} "
            "and year_of_loss between ? and ? group by year_of_loss", (*params, first, last))["rows"]}
    policies = {}
    if place is None:
        policies = dict(run_bound(db, "select year, policies from nfip_policies_by_year where county = ? "
                                      "and year between ? and ?", (county_name, first, last))["rows"])
    rows = []
    for year in range(first, last + 1):
        claims, paid_total = found.get(year, (0, 0))
        held = policies.get(year)
        rows.append({"year": year, "claims": claims, "paid_total": round(paid_total or 0, 2), "policies": held,
                     "claims_per_1000_policies": round(claims / held * 1000, 2) if held else None})
    totals = {"claims": sum(r["claims"] for r in rows), "paid_total": round(sum(r["paid_total"] for r in rows), 2)}
    tables = "nfip_claims" + (", nfip_policies_by_year" if place is None else ", places, place_tracts")
    return {"rows": rows, "totals": totals, "scope": scope, "from": f"{tables}; {who}; {first}–{last}"}


# ---- rain vs claims ------------------------------------------------------------------------------

TENTHS_MM_PER_INCH = 254  # COMPLETE_GAUGE_DAYS comes from data_access: the same rule as the year-by-year page


def rain_vs_claims(db: Database, *, county: str, year_from: int | None = None, year_to: int | None = None) -> dict:
    """Per year: mean rainfall over the county's gauges with a complete year, claims, and NOAA flood events."""
    name = normalize_county(county)
    first, last = year_range(db, "nfip_claims", "year_of_loss", year_from, year_to)
    rain = {y: (total, gauges) for y, total, gauges in run_bound(
        db, "select r.year, avg(case when r.days_reported >= ? then r.total_tenths_mm end), "
            "sum(r.days_reported >= ?) from rainfall_station_years r "
            "join weather_stations s on s.station_id = r.station_id "
            "where s.county = ? and r.year between ? and ? group by r.year",
        (COMPLETE_GAUGE_DAYS, COMPLETE_GAUGE_DAYS, name, first, last))["rows"]}
    claims = dict(run_bound(db, "select year_of_loss, count(*) from nfip_claims where county = ? "
                                "and year_of_loss between ? and ? group by year_of_loss", (name, first, last))["rows"])
    events = dict(run_bound(db, "select cast(substr(date, 1, 4) as integer), count(*) from flood_events "
                                "where county = ? and substr(date, 1, 4) between ? and ? group by 1",
                            (name, str(first), str(last)))["rows"])
    rows = []
    for year in range(first, last + 1):
        total, gauges = rain.get(year, (None, 0))
        rows.append({"year": year, "rain_in": round(total / TENTHS_MM_PER_INCH, 2) if total is not None else None,
                     "gauges": int(gauges or 0), "claims": claims.get(year, 0), "noaa_events": events.get(year, 0)})
    return {"rows": rows, "from": (f"rainfall_station_years (gauges with at least {COMPLETE_GAUGE_DAYS} days reported), "
                                   f"nfip_claims, flood_events; {name} county; {first}–{last}")}


# ---- lists: news and flood events ----------------------------------------------------------------

LIST_LIMIT = 10  # items returned by default
LIST_MAX = 25
NEWS_TOPICS = ("flood", "rain", "storm", "drought", "water_system", "water")
FAR_PAST, FAR_FUTURE = "0000-00-00", "9999-99-99"


def _limit(value: int | None) -> int:
    return max(1, min(int(value if value is not None else LIST_LIMIT), LIST_MAX))


def _day(value: str | None, default: str) -> str:
    """A YYYY-MM-DD bound, compared as text against ISO dates and timestamps."""
    if value is None:
        return default
    text = str(value).strip()
    try:
        if len(text) != 10:
            raise ValueError
        date.fromisoformat(text)
    except ValueError:
        raise ToolError(f"Dates must look like YYYY-MM-DD, not {value!r}.") from None
    return text


def _county_and_city(db: Database, county: str | None, place: str | None) -> tuple[str, str | None]:
    """The county to filter by, and the place's folded name to match on a city field (None for a county)."""
    county_name = _county_or_place(county, place)
    if place is None:
        return county_name, None
    match = _one_place(db, place)
    return match["county"], fold(match["name"])


def find_news(db: Database, *, county: str | None = None, place: str | None = None, topic: str | None = None,
              date_from: str | None = None, date_to: str | None = None, limit: int | None = None) -> dict:
    """Water news stories and official notices, newest first, never a rejected story. Each item lists the
    other outlets that told the same story (`also_reported_by`)."""
    county_name, city = _county_and_city(db, county, place)
    if topic is not None and topic not in NEWS_TOPICS:
        raise ToolError(f"Unknown topic {topic!r}. Use one of: {', '.join(NEWS_TOPICS)}.")
    start, end = _day(date_from, FAR_PAST), _day(date_to, FAR_FUTURE)
    rows = run_bound(db, "select id, headline, publisher, published_at, kind, source_url, city, topics "
                         "from news_articles where county = ? and substr(published_at, 1, 10) between ? and ? "
                         "order by published_at desc", (county_name, start, end), row_cap=5000)["rows"]
    picked = [r for r in rows
              if (city is None or fold(r[6] or "") == city)
              and (topic is None or topic in (r[7] or "").split(","))]
    items = []
    for story_id, headline, publisher, published_at, kind, source_url, _city, _topics in picked[:_limit(limit)]:
        copies = run_bound(db, "select publisher from news_article_copies where article_id = ? order by publisher",
                           (story_id,))["rows"]
        items.append({"headline": headline, "publisher": publisher, "published_at": published_at, "kind": kind,
                      "source_url": source_url, "also_reported_by": [c[0] for c in copies]})
    who = f"{place} ({county_name} county)" if place is not None else f"{county_name} county"
    return {"count": len(picked), "items": items,
            "from": f"news_articles (rejected stories excluded), news_article_copies; {who}"}


def flood_events(db: Database, *, county: str | None = None, place: str | None = None,
                 date_from: str | None = None, date_to: str | None = None, limit: int | None = None) -> dict:
    """NOAA Storm Events flood events and flood reports to NWS Brownsville, newest first. For a place, NWS
    reports are matched on their city; NOAA events are the place's whole county (`noaa_scope`)."""
    county_name, city = _county_and_city(db, county, place)
    start, end = _day(date_from, FAR_PAST), _day(date_to, FAR_FUTURE)
    n = _limit(limit)
    noaa = run_bound(db, "select date, type, location, summary, source_url from flood_events where county = ? "
                         "and date between ? and ? order by date desc", (county_name, start, end), row_cap=5000)["rows"]
    nws = run_bound(db, "select reported_at, kind, city, remark, source from nws_flood_reports where county = ? "
                        "and substr(reported_at, 1, 10) between ? and ? order by reported_at desc",
                    (county_name, start, end), row_cap=5000)["rows"]
    if city is not None:
        # NWS writes the town alone or as a distance and direction from it: "Weslaco", "3 ENE Weslaco".
        town = re.compile(rf"^(?:\d+(?:\.\d+)?\s+[nsew]{{1,3}}\s+)?{re.escape(city)}$")
        nws = [r for r in nws if town.match(fold(r[2] or ""))]
    result = {
        "noaa_count": len(noaa), "nws_count": len(nws),
        "noaa": [dict(zip(("date", "type", "location", "summary", "source_url"), r, strict=True)) for r in noaa[:n]],
        "nws": [dict(zip(("reported_at", "kind", "city", "remark", "source"), r, strict=True)) for r in nws[:n]],
        "from": f"flood_events (NOAA Storm Events), nws_flood_reports; {county_name} county",
    }
    if place is not None:
        result["noaa_scope"] = "county"
    return result
