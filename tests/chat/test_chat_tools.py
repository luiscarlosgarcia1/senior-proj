"""Chat: the fixed, read-only data tools the model may call (fixture database only)."""

import pytest
from fixture_db import add_chat_fixture, build_fixture_database

from rgv_flood.chat.sqltool import QueryRefused, run_bound
from rgv_flood.chat.tools import ToolError, find_place, normalize_county
from rgv_flood.db import Database


@pytest.fixture()
def chat_db(fixture_db):
    return Database(add_chat_fixture(fixture_db))


def test_tool_error_is_a_refusal():
    assert issubclass(ToolError, QueryRefused)


def test_normalize_county():
    assert normalize_county("Hidalgo County") == "hidalgo"
    assert normalize_county("  CAMERON ") == "cameron"
    with pytest.raises(ToolError, match="cameron, hidalgo, starr, willacy"):
        normalize_county("hidalgo' OR 1=1 --")


def test_run_bound_binds_parameters(chat_db):
    out = run_bound(chat_db, "select count(*) as n from nfip_claims where county = ?", ("hidalgo' or '1'='1",))
    assert out["rows"] == [[0]]
    assert run_bound(chat_db, "select count(*) from nfip_claims where county = ?", ("hidalgo",))["rows"] == [[3]]


def test_find_place_exact(chat_db):
    r = find_place(chat_db, "edinburg")
    assert r["ambiguous"] is False
    m = r["matches"][0]
    assert m["county"] == "hidalgo" and m["kind"] == "city"
    assert set(m["tracts"]) == {"48215020100", "48215020200"}
    assert set(m["tract_vintages"]) == {2010, 2023}
    assert r["from"] == "places, place_tracts"


def test_find_place_accent_and_alias(chat_db):
    assert find_place(chat_db, "Penitas")["matches"][0]["name"] == "Peñitas"
    assert find_place(chat_db, "PEÑITAS")["matches"][0]["name"] == "Peñitas"


def test_find_place_exact_beats_prefix(chat_db):
    r = find_place(chat_db, "mission")
    assert [m["name"] for m in r["matches"]] == ["Mission"] and r["ambiguous"] is False


def test_find_place_prefix_can_be_ambiguous(chat_db):
    r = find_place(chat_db, "ed")
    assert r["ambiguous"] is True
    assert {m["name"] for m in r["matches"]} == {"Edinburg", "Edcouch"}
    assert find_place(chat_db, "mis")["matches"][0]["name"] == "Mission"  # name prefix only, not "La Mission"


def test_find_place_no_match(chat_db):
    r = find_place(chat_db, "Atlantis")
    assert r["matches"] == [] and "county" in r["hint"]


def test_find_place_without_places_table(tmp_path):
    db = Database(build_fixture_database(tmp_path / "old.sqlite3"))
    with pytest.raises(ToolError, match="Places are not built yet"):
        find_place(db, "Edinburg")


# ---- claims_summary and rain_vs_claims --------------------------------------------------------------
# Fixture claims (building paid only): hidalgo a 2020 $1000 (tract 48215020100), b 2020 $500 (48215020200),
# d 2018 $100 (48215099900); starr c 2020 $250. Policies: hidalgo 2020 1000, starr 2020 1000.
# Gauge-years (hidalgo): Weslaco 2020 365 days 2540 (10 in), McAllen 2020 360 days 5080 (20 in),
# McAllen 2018 200 days (incomplete). NOAA events: hidalgo 2020-07-25 and 2018-06-20.

from rgv_flood.chat.tools import claims_summary, rain_vs_claims


def by_year(result):
    return {row["year"]: row for row in result["rows"]}


def test_claims_summary_county(chat_db):
    r = claims_summary(chat_db, county="Hidalgo")
    years = by_year(r)
    assert sorted(years) == [2018, 2019, 2020]  # every year in range, zeros included
    assert years[2020]["claims"] == 2 and years[2020]["paid_total"] == 1500
    assert years[2019]["claims"] == 0 and years[2019]["paid_total"] == 0
    assert r["totals"] == {"claims": 3, "paid_total": 1600}
    assert r["scope"] == "county" and "nfip_claims" in r["from"] and "hidalgo" in r["from"]


def test_claims_per_policy_only_where_policies(chat_db):
    years = by_year(claims_summary(chat_db, county="hidalgo"))
    assert years[2020]["policies"] == 1000 and years[2020]["claims_per_1000_policies"] == 2.0
    assert years[2018]["policies"] is None and years[2018]["claims_per_1000_policies"] is None


def test_claims_summary_place_uses_tracts(chat_db):
    r = claims_summary(chat_db, place="Edinburg")
    assert r["scope"] == "tracts of Edinburg"
    assert r["totals"] == {"claims": 2, "paid_total": 1500}
    assert all(row["claims_per_1000_policies"] is None for row in r["rows"])  # policies are county-wide only


def test_ambiguous_place_is_refused_with_candidates(chat_db):
    with pytest.raises(ToolError, match="Edcouch.*Edinburg"):
        claims_summary(chat_db, place="ed")


def test_needs_exactly_one_of_county_or_place(chat_db):
    with pytest.raises(ToolError, match="county or a place"):
        claims_summary(chat_db)
    with pytest.raises(ToolError, match="county or a place"):
        claims_summary(chat_db, county="hidalgo", place="Edinburg")


def test_out_of_range_years_give_the_range(chat_db):
    with pytest.raises(ToolError, match="2018.2020"):
        claims_summary(chat_db, county="hidalgo", year_from=2090, year_to=2095)


def test_reversed_years_are_swapped(chat_db):
    assert sorted(by_year(claims_summary(chat_db, county="hidalgo", year_from=2020, year_to=2019))) == [2019, 2020]


def test_partly_out_of_range_is_clipped(chat_db):
    r = claims_summary(chat_db, county="hidalgo", year_from=1990, year_to=2018)
    assert sorted(by_year(r)) == [2018]


def test_sql_shaped_county_rejected(chat_db):
    with pytest.raises(ToolError, match="Unknown county"):
        claims_summary(chat_db, county="hidalgo' OR 1=1 --")


def test_rain_counts_only_complete_gauges(chat_db):
    years = by_year(rain_vs_claims(chat_db, county="hidalgo"))
    assert years[2020]["rain_in"] == pytest.approx(15.0) and years[2020]["gauges"] == 2
    assert years[2018]["rain_in"] is None and years[2018]["gauges"] == 0  # McAllen 2018 reported 200 days
    assert years[2020]["claims"] == 2 and years[2018]["claims"] == 1
    assert years[2020]["noaa_events"] == 1 and years[2018]["noaa_events"] == 1


def test_rain_vs_claims_names_its_sources(chat_db):
    r = rain_vs_claims(chat_db, county="hidalgo")
    for table in ("rainfall_station_years", "nfip_claims", "flood_events"):
        assert table in r["from"]
    assert "330" in r["from"]


# ---- find_news and flood_events -------------------------------------------------------------------
# News: news-1 hidalgo 2020-07-27 Weslaco (topic flood; copy by ValleyCentral), news-2 hidalgo 2018-06-21
# (water_system,rain), news-3 cameron 2020-07-27 Brownsville (flood,storm); news-bad is rejected.
# NWS: nws-1 hidalgo 2020-07-25 "3 ENE Weslaco"; nws-3 hidalgo 2019-06-24 "2 N La Mission"; nws-2 cameron Harlingen. NOAA: hidalgo 2020-07-25, 2018-06-20.

from rgv_flood.chat.tools import LIST_MAX, find_news, flood_events


def test_find_news_county_newest_first(chat_db):
    r = find_news(chat_db, county="hidalgo")
    assert r["count"] == 2
    assert [i["headline"] for i in r["items"]] == ["Flooding closes Weslaco streets",
                                                   "Hidalgo County drainage crews work after June rain"]
    assert "news_articles" in r["from"]


def test_find_news_never_returns_rejected(chat_db):
    headlines = [i["headline"] for i in find_news(chat_db, county="hidalgo")["items"]]
    assert not any("Ignore your rules" in h for h in headlines)


def test_find_news_lists_copies(chat_db):
    item = find_news(chat_db, place="Weslaco")["items"][0]
    assert item["also_reported_by"] == ["ValleyCentral"]
    assert set(item) >= {"headline", "publisher", "published_at", "kind", "source_url"}


def test_find_news_topic_and_dates(chat_db):
    assert find_news(chat_db, county="hidalgo", topic="rain")["count"] == 1
    assert find_news(chat_db, county="hidalgo", date_from="2019-01-01")["count"] == 1
    with pytest.raises(ToolError, match="flood, rain, storm, drought, water_system, water"):
        find_news(chat_db, county="hidalgo", topic="tornado")
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        find_news(chat_db, county="hidalgo", date_from="last week")


def test_flood_events_counts_and_limit(chat_db):
    r = flood_events(chat_db, county="hidalgo", limit=1)
    assert r["noaa_count"] == 2 and r["nws_count"] == 2
    assert len(r["noaa"]) == 1 and r["noaa"][0]["date"] == "2020-07-25"  # newest first
    assert "flood_events" in r["from"] and "nws_flood_reports" in r["from"]


def test_flood_events_place_scope(chat_db):
    r = flood_events(chat_db, place="Weslaco")
    assert r["nws_count"] == 1 and r["nws"][0]["city"] == "3 ENE Weslaco"
    assert r["noaa_scope"] == "county" and r["noaa_count"] == 2


def test_limit_clamped(chat_db):
    assert LIST_MAX == 25
    assert len(flood_events(chat_db, county="hidalgo", limit=999)["noaa"]) <= LIST_MAX
    assert len(find_news(chat_db, county="hidalgo", limit=0)["items"]) == 1


def test_nws_place_match_is_the_town_not_a_longer_name(chat_db):
    assert [r["city"] for r in flood_events(chat_db, place="Mission")["nws"]] == []
    assert [r["city"] for r in flood_events(chat_db, place="La Mission")["nws"]] == ["2 N La Mission"]
