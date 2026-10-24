"""Read-only access to the central database.

Every query the app runs is in this module. The database is what the offline
pipeline produced (map layers, flood events, reports, weather) plus the live
signals the scheduler keeps current; `pipeline/database.py` defines its tables.
The app reads no data files and does not fetch from FEMA, TWDB, Census, or news
sites at request time.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, timedelta

from rgv_flood.db import Database

LAYER_COLUMNS = (
    "id, title, description, source, vintage, hazard_type, coverage, limitation, source_url, "
    "visualizations_json, feature_count, layer_group, panel_row, row_label, short_label, legend_json, "
    "parts_json, delivery, tiles_hash"
)
EVENT_COLUMNS = "id, county, date, date_end, type, location, precision, summary, source_url, geometry_note, lon, lat"
# How many of the wettest gauge-days the rainfall panel ranks.
RAINFALL_TOP_N = 15
# An event's rainfall and report context looks this many days either side of it.
# Daily rain totals usually run to a morning reading, so the rain that caused a
# flood is often booked to the following day.
CONTEXT_DAYS = 1
# How many gauges to show for an event that has a point to measure from.
NEAREST_GAUGES = 3
# News stories shown for an event: from the day before it began to a few days
# after it ended, since a story usually follows the flood it reports.
NEWS_DAYS_BEFORE = 1
NEWS_DAYS_AFTER = 3
NEWS_LIMIT = 200
NEWS_COLUMNS = "id, publisher, source_url, headline, published_at, excerpt, county, counties, city, places"


def _where(equals: dict[str, str | None]) -> tuple[str, tuple]:
    """A WHERE clause (and its parameters) for every column expression given a value."""
    wanted = {expression: value for expression, value in equals.items() if value}
    if not wanted:
        return "", ()
    return " where " + " and ".join(f"{expression} = ?" for expression in wanted), tuple(wanted.values())


# ---- map layers ----


def _layer(row: dict) -> dict:
    for name in ("visualizations", "legend", "parts"):
        row[name] = json.loads(row.pop(f"{name}_json"))
    return row


def available_layers(db: Database) -> list[dict]:
    """Every layer's descriptive metadata (not its geometry), in sidebar order."""
    return [_layer(row) for row in db.app_rows(f"select {LAYER_COLUMNS} from layers order by position")]


def layer_geojson_gzip(db: Database, layer_id: str, if_none_match: str = "") -> dict | None:
    """The layer's ETag and its FeatureCollection, gzipped exactly as the
    pipeline built it, in one query. `body` is None (the geometry isn't read)
    when `if_none_match` already names the ETag. None for an unknown layer."""
    rows = db.app_rows(
        """select etag, case when instr(:held, '"' || etag || '"') then null else geojson_gzip end as body
           from layers where id = :id""",
        {"id": layer_id, "held": if_none_match},
    )
    return rows[0] if rows else None


def layer_tile(db: Database, layer_id: str, z: int, x: int, y: int) -> dict | None:
    """{"data": one vector tile (gzipped MVT), or None where the layer has nothing}
    for a tiled layer; None for a layer that isn't tiled."""
    rows = db.app_rows(
        """select (select data from layer_tiles t where t.layer_id = l.id and z = ? and x = ? and y = ?) as data
           from layers l where l.id = ? and l.delivery = 'tiles'""",
        (z, x, y, layer_id),
    )
    return rows[0] if rows else None


# ---- flood events, reports, rainfall ----


def _events(db: Database, where: str = "", parameters: tuple = ()) -> list[dict] | None:
    query = f"select {EVENT_COLUMNS} from flood_events{where} order by date desc, id desc"
    return db.rows(query, parameters)


def flood_events(
    db: Database, year: str | None = None, county_slug: str | None = None, event_type: str | None = None
) -> list[dict]:
    """Event rows (newest first), optionally filtered to one year, county and/or type.

    ``lat`` / ``lon`` are None when the event has no point to fly the map to.
    """
    return _events(db, *_where({"substr(date, 1, 4)": year, "county": county_slug, "type": event_type})) or []


def flood_event_types(db: Database, county_slug: str | None = None) -> list[str]:
    where, parameters = _where({"county": county_slug})
    return [row["type"] for row in db.app_rows(f"select distinct type from flood_events{where} order by type", parameters)]


def flood_event_count(db: Database) -> int:
    rows = db.app_rows("select count(*) as total from flood_events")
    return rows[0]["total"] if rows else 0


def flood_event_years(db: Database, county_slug: str | None = None) -> list[str]:
    where, parameters = _where({"county": county_slug})
    rows = db.app_rows(f"select distinct substr(date, 1, 4) as year from flood_events{where} order by year desc", parameters)
    return [row["year"] for row in rows]


def flood_events_geojson(db: Database) -> dict | None:
    """Every event as a GeoJSON feature for the map (None before the first build)."""
    events = _events(db)
    if events is None:
        return None
    features = []
    for event in events:
        lon, lat = event.pop("lon"), event.pop("lat")
        geometry = {"type": "Point", "coordinates": [lon, lat]} if lat is not None else None
        features.append({"type": "Feature", "geometry": geometry, "properties": event})
    return {"type": "FeatureCollection", "features": features}


def flood_reports(db: Database, county_slug: str | None = None) -> list[dict]:
    """Local-news and local-government reports tied to documented flood events.

    Historical only — never live closure data. Each report carries its source
    URL and the date of the event it describes. Oldest first.
    """
    where, parameters = _where({"county": county_slug})
    return db.app_rows(f"select * from flood_reports{where} order by event_date, rowid", parameters)


def _inches(tenths_of_mm: float, digits: int) -> float:
    """GHCN-Daily stores rain in tenths of a millimetre."""
    return round(tenths_of_mm / 254.0, digits)


def rainfall_records(db: Database, county_slug: str | None = None) -> list[dict]:
    """The wettest single gauge-days on record (date, mm, inches, station):
    one county's own records when a county is given, otherwise the wettest
    across all four."""
    in_county, parameters = (" and s.county = ?", (county_slug,)) if county_slug else ("", ())
    wettest = db.app_rows(
        f"""select s.county, o.date, o.value as tenths_of_mm, s.name as station
            from weather_observations o join weather_stations s using (station_id)
            where o.element = 'PRCP' and o.value > 0{in_county}
            order by o.value desc, s.county, o.station_id, o.date
            limit ?""",
        (*parameters, RAINFALL_TOP_N),
    )
    days = []
    for row in wettest:
        tenths = row.pop("tenths_of_mm")
        days.append({**row, "mm": round(tenths / 10.0, 1), "inches": _inches(tenths, 1)})
    return days


# ---- what else is known about one flood event ----


def flood_event(db: Database, event_id: str) -> dict | None:
    rows = _events(db, " where id = ?", (event_id,))
    return rows[0] if rows else None


def _days_around(event: dict) -> tuple[date, date, date]:
    """(first day, the day the event began, last day) of an event's context window."""
    began = date.fromisoformat(event["date"])
    ended = date.fromisoformat(event["date_end"] or event["date"])
    return began - timedelta(days=CONTEXT_DAYS), began, max(began, ended) + timedelta(days=CONTEXT_DAYS)


def _km_between(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance (haversine)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def rainfall_near_event(db: Database, event: dict) -> dict:
    """Daily rain at gauges in the event's county, from the day before it began
    to the day after it ended.

    With a point to measure from, the nearest few gauges that reported are
    listed, nearest first; without one, every gauge in the county that reported.
    """
    first, began, last = _days_around(event)
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    readings = db.app_rows(
        """select s.station_id, s.name, s.lon, s.lat, o.date, o.value
           from weather_stations s cross join weather_observations o using (station_id)
           where s.county = ? and o.date between ? and ? and o.element = 'PRCP'""",
        (event["county"], first.isoformat(), last.isoformat()),
    )
    gauges: dict[str, dict] = {}
    for row in readings:
        gauge = gauges.setdefault(row["station_id"], {"name": row["name"], "distance_km": None, "by_day": {}})
        gauge["by_day"][row["date"]] = _inches(row["value"], 2)
        if event["lat"] is not None:
            gauge["distance_km"] = round(_km_between(event["lon"], event["lat"], row["lon"], row["lat"]))

    located = event["lat"] is not None
    ordered = sorted(gauges.values(), key=lambda g: (g["distance_km"], g["name"]) if located else (0, g["name"]))
    return {
        "days": [{"date": day.isoformat(), "label": f"{day:%b} {day.day}", "began": day == began} for day in days],
        "gauges": [
            {**gauge, "inches": [gauge["by_day"].get(day.isoformat()) for day in days]}
            for gauge in (ordered[:NEAREST_GAUGES] if located else ordered)
        ],
        "located": located,
    }


def reports_near_event(db: Database, event: dict) -> list[dict]:
    """Curated local reports from the event's county and the same days.

    Reports about one flood share a group. If a group's dates overlap the
    event's (give or take a day), the whole group is returned, so a report
    written days into a long flood still appears with the event that began it.
    Nothing links a report to one NOAA event, so this is a match on place and
    date, and the page says so.
    """
    first, _, last = _days_around(event)
    return db.app_rows(
        """with flood as (
             select coalesce(duplicate_group, id) as name,
                    min(event_date) as first_day,
                    max(coalesce(event_end, event_date)) as last_day
             from flood_reports where county = :county group by name
           )
           select r.* from flood_reports r
           join flood on flood.name = coalesce(r.duplicate_group, r.id)
           where r.county = :county and flood.first_day <= :last and flood.last_day >= :first
           order by r.event_date, r.rowid""",
        {"county": event["county"], "first": first.isoformat(), "last": last.isoformat()},
    )


def nws_reports_near_event(db: Database, event: dict) -> list[dict]:
    """Flooding reported to the National Weather Service in the event's county
    on the event's days (the same window as its rain and curated reports)."""
    first, _, last = _days_around(event)
    return db.app_rows(
        """select id, county, kind, reported_at, city, remark, source, magnitude, lon, lat
           from nws_flood_reports
           where county = ? and substr(reported_at, 1, 10) between ? and ?
           order by reported_at, id""",
        (event["county"], first.isoformat(), last.isoformat()),
    )


def _news_rows(db: Database, query: str, parameters: tuple | dict = ()) -> list[dict]:
    """News rows with `counties` as a list. Empty when the database was built
    before news existed (no such table)."""
    try:
        rows = db.app_rows(query, parameters)
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        return []
    for row in rows:
        row["counties"] = [slug for slug in row["counties"].split(",") if slug]
    return rows


def news_articles(db: Database, county_slug: str | None = None, year: int | None = None) -> list[dict]:
    """Flood news stories, newest first (at most NEWS_LIMIT), optionally for one
    county (any story that names it) and/or one year of publication."""
    conditions, parameters = [], []
    if county_slug:
        conditions.append("(county = ? or ',' || counties || ',' like ?)")
        parameters += [county_slug, f"%,{county_slug},%"]
    if year:
        conditions.append("substr(published_at, 1, 4) = ?")
        parameters.append(str(year))
    where = f" where {' and '.join(conditions)}" if conditions else ""
    return _news_rows(
        db,
        f"select {NEWS_COLUMNS} from news_articles{where} order by published_at desc, id limit {NEWS_LIMIT}",
        tuple(parameters),
    )


def news_near_event(db: Database, event: dict) -> list[dict]:
    """News stories that name the event's county and were published from the day
    before the event began to a few days after it ended, oldest first.

    Nothing links a story to one NOAA event, so this is a match on place and
    date, and the page says so.
    """
    began = date.fromisoformat(event["date"])
    ended = max(began, date.fromisoformat(event["date_end"] or event["date"]))
    return _news_rows(
        db,
        f"""select {NEWS_COLUMNS} from news_articles
            where (county = :county or ',' || counties || ',' like :like)
              and substr(published_at, 1, 10) between :first and :last
            order by published_at, id""",
        {
            "county": event["county"],
            "like": f"%,{event['county']},%",
            "first": (began - timedelta(days=NEWS_DAYS_BEFORE)).isoformat(),
            "last": (ended + timedelta(days=NEWS_DAYS_AFTER)).isoformat(),
        },
    )


# ---- provenance ----


def built_at(db: Database) -> str | None:
    """When the pipeline last finished building the database (None if unknown)."""
    try:
        return db.scalar("select value from build_info where key = 'built_at'")
    except sqlite3.OperationalError:  # a database built before build_info existed
        return None


def data_sources(db: Database) -> list[dict]:
    """Every dataset in the database: who published it, when it was fetched,
    how many records it holds. Events, weather and reports first, then layers."""
    return db.app_rows("select * from data_sources order by id like 'layer:%', dataset")


# ---- live signals ----

# Columns of the live_signals table that each consumer needs.
MAP_SIGNAL_COLUMNS = (
    "source", "native_id", "source_url", "source_publisher", "source_channel", "summary",
    "source_attributes_json", "county_slugs_json", "inclusion_basis", "source_geometry_json",
    "published_at", "effective_at", "source_updated_at", "expires_at", "first_seen_at",
    "last_seen_at", "retrieved_at",
)
SIDEBAR_SIGNAL_COLUMNS = (
    "source", "native_id", "source_url", "source_publisher", "source_channel", "summary",
    "county_slugs_json", "source_geometry_json", "geometry_absence_reason", "is_mappable",
    "published_at", "effective_at", "source_updated_at", "expires_at", "last_seen_at", "retrieved_at",
)


def _active_official_signals(db: Database,
    columns: tuple[str, ...], *, only_mappable: bool, order_by: str = ""
) -> list[dict] | None:
    """Active, official live signals (None if the database doesn't exist yet)."""
    return db.rows(
        f"select {', '.join(columns)} from live_signals "
        "where lifecycle_state = 'active' and provenance = 'official'"
        + (" and is_mappable = 1" if only_mappable else "")
        + (f" order by {order_by}" if order_by else ""),
    )


def active_official_signal_features(db: Database) -> dict | None:
    """Active official signals that carry source geometry, as GeoJSON for the map."""
    rows = _active_official_signals(db, MAP_SIGNAL_COLUMNS, only_mappable=True)
    if rows is None:
        return None
    features = []
    for row in rows:
        geometry = json.loads(row.pop("source_geometry_json"))
        row["source_attributes"] = json.loads(row.pop("source_attributes_json"))
        row["county_slugs"] = json.loads(row.pop("county_slugs_json"))
        features.append({"type": "Feature", "geometry": geometry, "properties": row})
    return {"type": "FeatureCollection", "features": features}


def active_official_signals(db: Database, county_slug: str | None = None) -> list[dict]:
    """Active official signals for the sidebar, including notices.

    Signals without source geometry stay in this list so the UI can link to
    them without inventing a map location.
    """
    rows = _active_official_signals(db,
        SIDEBAR_SIGNAL_COLUMNS, only_mappable=False, order_by="retrieved_at desc, source_publisher, summary"
    )
    signals = []
    for row in rows or []:
        row["county_slugs"] = json.loads(row.pop("county_slugs_json"))
        row["is_mappable"] = bool(row["is_mappable"])
        if county_slug is None or county_slug in row["county_slugs"]:
            signals.append(row)
    return signals


def live_signals_refreshed_at(db: Database) -> str | None:
    """When a live-alert poll last finished (None before the first one)."""
    return db.scalar("select max(completed_at) from live_signal_runs where is_complete = 1")


# ---- year by year: claims beside rainfall ----

# Claims start in 1978; so does every county's long rain record. The current
# year is left out until it is over.
HISTORY_FIRST_YEAR = 1978
# A gauge's year counts toward yearly rainfall only if it reported rain on at
# least this many days; otherwise missing days would read as dry ones.
COMPLETE_GAUGE_DAYS = 330


def _by_year(db: Database, query: str, county_slug: str | None, county_column: str = "county") -> dict[int, dict]:
    """Rows of a per-year query, keyed by year, optionally for one county."""
    where = f" and {county_column} = :county" if county_slug else ""
    rows = db.app_rows(query.format(where=where), {"county": county_slug, "first": HISTORY_FIRST_YEAR})
    return {row.pop("year"): row for row in rows}


def _ranks(values: list[float]) -> list[float]:
    """Ranks from 1, ties sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def rank_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Spearman's rank correlation: how closely two series rise and fall
    together, from -1 to 1, without letting one extreme year dominate."""
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mean = (len(xs) + 1) / 2
    covariance = sum((a - mean) * (b - mean) for a, b in zip(rx, ry, strict=True))
    spread = (sum((a - mean) ** 2 for a in rx) * sum((b - mean) ** 2 for b in ry)) ** 0.5
    return round(covariance / spread, 2) if spread else None


def history_by_year(db: Database, county_slug: str | None, last_year: int) -> dict:
    """Every year from 1978 to `last_year`: flood-insurance claims and what they
    paid, policies in force, the year's rain and its wettest day."""
    claims = _by_year(db,
        """select year_of_loss as year, count(*) as claims,
                  sum(paid_building + paid_contents + paid_increased_cost_of_compliance) as paid
           from nfip_claims where year_of_loss >= :first{where} group by year_of_loss""",
        county_slug,
    )
    named = _by_year(db,
        """select year_of_loss as year, flood_event, count(*) as n from nfip_claims
           where year_of_loss >= :first and flood_event is not null{where}
           group by year_of_loss, flood_event order by n""",  # the last row per year wins: the biggest
        county_slug,
    )
    policies = _by_year(db, "select year, sum(policies) as policies from nfip_policies_by_year where 1=1{where} group by year", county_slug)
    rain = _by_year(db,
        f"""select r.year,
                   avg(case when r.days_reported >= {COMPLETE_GAUGE_DAYS} then r.total_tenths_mm end) as total_tenths_mm,
                   sum(r.days_reported >= {COMPLETE_GAUGE_DAYS}) as complete_gauges,
                   max(case when r.days_reported >= {COMPLETE_GAUGE_DAYS} then r.wettest_day_tenths_mm end)
                       as wettest_tenths_mm
            from rainfall_station_years r join weather_stations s using (station_id)
            where r.year >= :first{{where}} group by r.year""",
        county_slug,
        county_column="s.county",
    )

    years = []
    for year in range(HISTORY_FIRST_YEAR, last_year + 1):
        c, p, r = claims.get(year, {}), policies.get(year), rain.get(year, {})
        count = c.get("claims", 0)
        annual = r.get("total_tenths_mm") if r.get("complete_gauges") else None
        years.append({
            "year": year,
            "claims": count,
            "paid": round(c.get("paid") or 0),
            "flood_event": (named.get(year) or {}).get("flood_event"),
            "policies": p["policies"] if p else None,
            "claims_per_1000_policies": round(1000 * count / p["policies"], 1) if p and p["policies"] else None,
            "rain_inches": round(annual / 254, 1) if annual is not None else None,
            "complete_gauges": r.get("complete_gauges") or 0,
            "wettest_day_inches": round(r["wettest_tenths_mm"] / 254, 2) if r.get("wettest_tenths_mm") else None,
        })

    with_rain = [y for y in years if y["rain_inches"] is not None and y["wettest_day_inches"] is not None]
    worst = max(years, key=lambda y: y["claims"])
    return {
        "years": years,
        "totals": {
            "claims": sum(y["claims"] for y in years),
            "paid": sum(y["paid"] for y in years),
            "worst_year": worst["year"] if worst["claims"] else None,
            "worst_year_claims": worst["claims"],
            "worst_year_event": worst["flood_event"],
        },
        "correlation": {
            "years": len(with_rain),
            "with_annual_rain": rank_correlation([y["claims"] for y in with_rain], [y["rain_inches"] for y in with_rain]),
            "with_wettest_day": rank_correlation([y["claims"] for y in with_rain], [y["wettest_day_inches"] for y in with_rain]),
        },
    }
