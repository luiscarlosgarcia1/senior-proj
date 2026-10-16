"""A small, complete database for the app's tests: two flood events, three
gauges with readings, curated reports, sources, layers and claims history.

`build_fixture_database(path)` writes it; tests that need variations build on it
with `pipeline/database.py`'s `replace_table`.
"""

import gzip

from database import open_database, record_sources, replace_table


def _event(event_id: str, date: str, **values) -> dict:
    return {
        "id": event_id,
        "county": "hidalgo",
        "date": date,
        "date_end": None,
        "type": "Flood",
        "location": "Hidalgo County, Texas",
        "precision": "county",
        "summary": "test event",
        "narrative": "test narrative",
        "source_url": "https://example.test/noaa",
        "source_lon": values.get("lon"),
        "source_lat": values.get("lat"),
        "geometry_note": None,
        "lon": None,
        "lat": None,
        **values,
    }


EVENTS = [
    _event(
        "noaa-storm-events-1",
        "2020-07-25",
        type="Flash flood",
        location="WESLACO, Hidalgo County, Texas",
        source_url="https://example.test/1",
        lon=-98.2,
        lat=26.2,
    ),
    _event("noaa-storm-events-2", "2018-06-20", summary="test event without a point"),
]
WESLACO, MCALLEN, RIO_GRANDE_CITY = "USC00419588", "USW00012959", "USC00417622"


def _station(station_id: str, county: str, name: str, lon: float, lat: float) -> dict:
    return {
        "station_id": station_id, "county": county, "name": name, "lon": lon, "lat": lat,
        "elevation_m": 20.0, "source_url": f"https://example.test/{station_id}.csv.gz",
    }


STATIONS = [
    _station(WESLACO, "hidalgo", "Weslaco", -97.97, 26.18),
    _station(MCALLEN, "hidalgo", "McAllen Airport", -98.24, 26.18),
    _station(RIO_GRANDE_CITY, "starr", "Rio Grande City", -98.81, 26.38),
]


def _reading(station_id: str, date: str, element: str, value: int) -> dict:
    return {
        "station_id": station_id, "date": date, "element": element, "value": value,
        "measurement_flag": None, "source_flag": "7", "observation_time_flag": None,
    }


# PRCP is tenths of a millimetre: 2184 is 218.4 mm, or 8.6 inches.
READINGS = [
    _reading(WESLACO, "2025-03-28", "PRCP", 2184),
    _reading(WESLACO, "2025-03-29", "PRCP", 100),
    _reading(WESLACO, "2025-03-30", "PRCP", 0),  # a dry day is not a rainfall record
    _reading(WESLACO, "2025-03-28", "TMAX", 9999),  # nor is a temperature
    _reading(RIO_GRANDE_CITY, "2010-07-01", "PRCP", 508),  # 2.0 in: Starr's own record
    # around the 2020-07-25 event at (-98.2, 26.2): McAllen is the nearer gauge
    _reading(WESLACO, "2020-07-24", "PRCP", 0),
    _reading(WESLACO, "2020-07-26", "PRCP", 1270),  # 5.00 in
    _reading(MCALLEN, "2020-07-25", "PRCP", 254),  # 1.00 in
]


def _report(report_id: str, event_date: str, **values) -> dict:
    return {
        "id": report_id,
        "county": "hidalgo",
        "headline": f"Headline of {report_id}.",
        "detail": f"Headline of {report_id}. More detail.",
        "location": "Weslaco, Hidalgo County, Texas",
        "location_precision": "municipality",
        "event_date": event_date,
        "event_end": None,
        "published_at": event_date,
        "publisher": "KRGV Channel 5 News",
        "channel": "local_news",
        "source_url": f"https://example.test/{report_id}",
        "original_content": None,
        "duplicate_group": None,
        "retrieved_at": "2026-09-04T03:17:42Z",
        **values,
    }


REPORTS = [
    _report("hanna-landfall", "2020-07-25", duplicate_group="hanna"),
    _report("hanna-recovery", "2020-07-31", duplicate_group="hanna"),  # days later, same flood
    _report("weslaco-streets", "2021-05-19"),
]
SOURCES = [
    {
        "id": "noaa-storm-events", "publisher": "NOAA NCEI", "dataset": "Storm Events Database",
        "url": "https://example.test/storm", "retrieved_at": "2026-09-16T04:30:40Z", "record_count": 1425,
        "notes": None,
    },
    {
        "id": "layer:fema-nfhl", "publisher": "FEMA", "dataset": "FEMA effective flood hazard (NFHL)",
        "url": None, "retrieved_at": None, "record_count": 20, "notes": None,
    },
]


def _layer(layer_id: str, geojson: str = '{"type":"FeatureCollection","features":[]}', **values) -> dict:
    """A `layers` row with every column the app reads."""
    return {
        "id": layer_id,
        "position": 0,
        "title": layer_id.title(),
        "description": None,
        "source": "Somewhere",
        "vintage": None,
        "hazard_type": None,
        "coverage": None,
        "limitation": None,
        "source_url": None,
        "visualizations_json": "[]",
        "layer_group": "hazard",
        "panel_row": layer_id,
        "row_label": layer_id.title(),
        "short_label": layer_id.title(),
        "legend_json": '{"shape": "sev", "color": "nfhl"}',
        "parts_json": "[]",
        "delivery": "geojson",
        "tiles_hash": None,
        "feature_count": 0,
        "geojson_gzip": gzip.compress(geojson.encode()),
        "etag": f"etag-of-{layer_id}",
        **values,
    }


def _claim(claim_id: str, county: str, date: str, paid: float, flood_event: str | None = None) -> dict:
    return {
        "id": claim_id, "county": county, "date_of_loss": date, "year_of_loss": int(date[:4]),
        "flood_event": flood_event, "cause_of_damage": None, "paid_building": paid, "paid_contents": 0.0,
        "paid_increased_cost_of_compliance": 0.0, "building_damage": None, "contents_damage": None,
        "rated_flood_zone": None, "occupancy_type": None, "census_tract": None, "lon": None, "lat": None,
    }


def _gauge_year(station_id: str, year: int, days: int, total: float, wettest: float) -> dict:
    return {"station_id": station_id, "year": year, "days_reported": days, "total_tenths_mm": total,
            "wettest_day_tenths_mm": wettest, "days_over_2_inches": 0}


CLAIMS = [
    _claim("a", "hidalgo", "2020-07-26", 1000, "Hurricane Hanna"),
    _claim("b", "hidalgo", "2020-07-27", 500, "Hurricane Hanna"),
    _claim("c", "starr", "2020-09-01", 250),
    _claim("d", "hidalgo", "2018-06-20", 100),
]
POLICIES = [
    {"county": "hidalgo", "year": 2020, "policies": 1000},
    {"county": "starr", "year": 2020, "policies": 1000},
]
GAUGE_YEARS = [
    _gauge_year(WESLACO, 2020, 365, 2540, 1270),  # 10 in; wettest day 5 in
    _gauge_year(MCALLEN, 2020, 360, 5080, 254),  # 20 in
    _gauge_year(MCALLEN, 2018, 200, 99999, 9999),  # too many days missing to count
]


PHOTOS_GEOJSON = (
    '{"type":"FeatureCollection","features":['
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[-98.2,26.2]},'
    '"properties":{"overlay_type":"flood_photo","event":"June 2019","photo_url":"https://services7.arcgis.com/x/1"}},'
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[-98.1,26.3]},'
    '"properties":{"overlay_type":"flood_photo","event":"June 2018"}}]}'
)
LAYERS = [
    _layer("county-boundaries", position=0, layer_group="base", short_label="County boundaries",
           legend_json='{"shape": "line", "color": "county"}'),
    _layer("fema-nfhl", position=1, title="FEMA effective flood hazard (NFHL)", feature_count=20,
           row_label="FEMA effective flood hazard (NFHL)", short_label="FEMA effective flood hazard (NFHL)"),
    _layer("twdb-cursory-1in100", position=2, panel_row="twdb", row_label="TWDB modeled flood extent",
           short_label="1% annual chance", legend_json='{"shape": "sev", "color": "sev-high"}',
           delivery="tiles", tiles_hash="abc123def456"),
    _layer("twdb-cursory-1in500", position=3, panel_row="twdb", row_label="TWDB modeled flood extent",
           short_label="0.2% annual chance", legend_json='{"shape": "sev", "color": "sev-mod"}'),
    _layer("waterways", position=4, layer_group="works", legend_json='{"shape": "line", "color": "drain"}'),
    _layer("hcdd1-flood-photos", PHOTOS_GEOJSON, position=5, layer_group="evidence", feature_count=2,
           legend_json='{"shape": "dot", "color": "photos"}',
           parts_json='[{"id": "photos", "label": "Photos you can open", "filter": ["has", "photo_url"], "color": "photos"},'
                      ' {"id": "locations", "label": "Photo locations only", "filter": ["!", ["has", "photo_url"]],'
                      ' "color": "photoloc"}]'),
    _layer("flood-projects", position=6, layer_group="projects", legend_json='{"shape": "sqf", "color": "sfp"}'),
    _layer("dams", position=9, layer_group="works", row_label="Dams", short_label="Dams",
           legend_json='{"shape": "dot", "color": "dam"}'),
]
# One real-looking tile of twdb-cursory-1in100 (the bytes only need to be gzip).
TILES = [{"layer_id": "twdb-cursory-1in100", "z": 10, "x": 232, "y": 434, "data": gzip.compress(b"mvt")}]


NWS_REPORTS = [
    {"id": "nws-1", "county": "hidalgo", "kind": "flash_flood", "reported_at": "2020-07-25T23:10:00Z",
     "city": "3 ENE Weslaco", "remark": "Streets flooded.", "source": "Law Enforcement", "magnitude": None,
     "lon": -97.95, "lat": 26.17},
    {"id": "nws-2", "county": "cameron", "kind": "flood", "reported_at": "2020-07-25T20:00:00Z",
     "city": "Harlingen", "remark": "Water in homes.", "source": "Public", "magnitude": None,
     "lon": -97.7, "lat": 26.19},
]


def build_fixture_database(path, *, history: bool = False):
    """Write the fixture database to `path` and return it. `history` adds claims,
    policies and gauge-years for the year-by-year page."""
    with open_database(path) as connection:
        replace_table(connection, "flood_events", EVENTS)
        replace_table(connection, "flood_reports", REPORTS)
        replace_table(connection, "weather_stations", STATIONS)
        replace_table(connection, "weather_observations", READINGS)
        record_sources(connection, SOURCES)
        replace_table(connection, "layers", LAYERS)
        replace_table(connection, "layer_tiles", TILES)
        replace_table(connection, "nws_flood_reports", NWS_REPORTS)
        replace_table(connection, "build_info", [{"key": "built_at", "value": "2026-10-15T12:00:00Z"}])
        if history:
            replace_table(connection, "nfip_claims", CLAIMS)
            replace_table(connection, "nfip_policies_by_year", POLICIES)
            replace_table(connection, "rainfall_station_years", GAUGE_YEARS)
    return path
