"""API: what the news archive says, measured against the data (/api/v1/news/insights), a day-by-day timeline of the
stories around a date (/api/v1/news/timeline), and "also reported by" from the copies cleaning set aside."""

import sqlite3
from contextlib import closing
from datetime import date

import pytest

from rgv_flood import data_access
from rgv_flood.db import Database

THROUGH = date(2020, 12, 31)


def run(connection_path, sql, *parameters):
    with closing(sqlite3.connect(connection_path)) as connection, connection:
        connection.execute(sql, parameters)


def insights(fixture_db, county=None):
    return data_access.news_insights(Database(fixture_db), county, THROUGH)


# ---- news against rain, NWS reports and flood-insurance claims, month by month ----

def test_every_month_from_2017_is_counted_with_the_measurements_beside_it(fixture_db):
    months = {m["month"]: m for m in insights(fixture_db)["months"]}

    assert next(iter(months)) == "2017-01" and list(months)[-1] == "2020-12" and len(months) == 48
    july = months["2020-07"]
    assert july == {"month": "2020-07", "stories": 2, "rain_inches": 7.5, "nws_reports": 2, "claims": 2}
    assert months["2018-06"] == {"month": "2018-06", "stories": 1, "rain_inches": None, "nws_reports": 0, "claims": 1}
    assert months["2019-03"]["stories"] == 0


def test_only_flood_rain_and_storm_stories_are_counted_against_the_weather(fixture_db):
    run(fixture_db, "update news_articles set topics = 'drought' where id = 'news-3'")

    july = next(m for m in insights(fixture_db)["months"] if m["month"] == "2020-07")

    assert july["stories"] == 1


def test_a_county_has_its_own_stories_rain_reports_and_claims(fixture_db):
    july = next(m for m in insights(fixture_db, "cameron")["months"] if m["month"] == "2020-07")

    assert july == {"month": "2020-07", "stories": 1, "rain_inches": None, "nws_reports": 1, "claims": 0}


def test_the_correlations_are_rank_correlations_over_the_months_that_have_each_measure(fixture_db):
    result = insights(fixture_db)["correlation"]

    assert set(result) == {"months", "rain_months", "rain", "rain_next_month", "nws", "claims"}
    assert result["months"] == 48 and result["rain_months"] == 2  # only June and July 2020 have a complete gauge month
    assert result["rain"] is None  # two months are too few to say
    assert -1 <= result["nws"] <= 1 and -1 <= result["claims"] <= 1


def test_wet_months_with_little_news_and_news_heavy_months_with_little_rain_are_named(fixture_db):
    result = insights(fixture_db)

    assert {"wet_quiet", "loud_dry"} <= set(result) and isinstance(result["wet_quiet"], list)


# ---- the busiest days ----

def test_the_busiest_days_count_stories_and_outlets(fixture_db):
    (first, *_) = insights(fixture_db)["busiest_days"]

    assert first["date"] == "2020-07-27" and first["stories"] == 2 and first["outlets"] == 1
    assert first["headline"] in {"Flooding closes Weslaco streets", "Brownsville flooding strands drivers"}


# ---- coverage against what happened, county by county ----

def test_coverage_compares_each_countys_stories_with_its_claims_and_nws_reports(fixture_db):
    coverage = {row["county"]: row for row in insights(fixture_db)["coverage"]}

    assert list(coverage) == ["cameron", "hidalgo", "starr", "willacy"]
    assert coverage["hidalgo"] == {"county": "hidalgo", "stories": 2, "claims": 3, "nws_reports": 1,
                                   "stories_per_100_claims": 66.7, "stories_per_nws_report": 2.0}
    assert coverage["cameron"]["stories_per_100_claims"] is None  # no claims: no ratio, not infinity
    assert coverage["starr"]["stories_per_100_claims"] == 0.0


def test_valley_wide_stories_are_not_credited_to_any_one_county(fixture_db):
    run(fixture_db, "update news_articles set county = null, counties = '' where id = 'news-1'")

    coverage = {row["county"]: row["stories"] for row in insights(fixture_db)["coverage"]}

    assert coverage["hidalgo"] == 1


# ---- recurring trouble spots ----

def test_streets_and_waterways_named_in_two_or_more_stories_are_ranked(fixture_db):
    run(fixture_db, "update news_articles set places = 'Military Highway; North Main Drain' where id = 'news-1'")
    run(fixture_db, "update news_articles set places = 'The Military Highway' where id = 'news-2'")
    run(fixture_db, "update news_articles set places = 'State Highway; North Main Drain' where id = 'news-3'")

    places = insights(fixture_db)["places"]

    assert [(p["name"], p["stories"]) for p in places] == [("Military Highway", 2), ("North Main Drain", 2)]
    assert places[0]["first"] == "2018-06-21" and places[0]["last"] == "2020-07-27"
    assert places[0]["latest_url"] == "https://example.test/news/news-1"


# ---- water-system problems, town by town ----

def test_water_system_problems_are_counted_by_town(fixture_db):
    run(fixture_db, "update news_articles set matched_terms = 'boil water', topics = 'water_system' where id = 'news-1'")
    run(fixture_db, "update news_articles set matched_terms = 'water pressure,drainage', city = 'Weslaco' where id = 'news-2'")
    run(fixture_db, "update news_articles set matched_terms = 'drainage' where id = 'news-3'")  # a project, not a problem

    (weslaco,) = insights(fixture_db)["water_systems"]

    assert weslaco["city"] == "Weslaco" and weslaco["stories"] == 2 and weslaco["county"] == "hidalgo"
    assert weslaco["first"] == "2018-06-21" and weslaco["last"] == "2020-07-27"
    assert weslaco["latest_headline"] == "Flooding closes Weslaco streets"


# ---- languages ----

@pytest.mark.parametrize("headline, spanish", [
    ("Alerta de Hervir el Agua para Weslaco", True),
    ("Ciudad de Mission se prepara para temporada de huracanes", True),
    ("La Joya ISD student speaks out on school's water park", False),
    ("Flooding closes Weslaco streets", False),
    ("Los Fresnos residents clean up after storm", False),
])
def test_a_headline_is_called_spanish_only_with_more_than_a_place_name_to_go_on(headline, spanish):
    assert data_access.headline_is_spanish(headline) is spanish


def test_the_share_of_spanish_headlines_is_counted(fixture_db):
    run(fixture_db, "update news_articles set headline = 'Alerta de inundaciones para el condado' where id = 'news-3'")

    assert insights(fixture_db)["languages"] == {"spanish": 1, "english": 2}


# ---- the endpoint ----

def test_the_insights_endpoint(api_client):
    body = api_client.get("/api/v1/news/insights").json()

    assert body["first_year"] == 2017 and body["months"][0]["month"] == "2017-01"
    assert {"months", "correlation", "busiest_days", "coverage", "places", "water_systems", "languages"} <= set(body)


def test_insights_without_a_news_table_are_empty(make_client, fixture_db):
    run(fixture_db, "drop table news_articles")

    body = make_client(fixture_db).get("/api/v1/news/insights").json()

    assert body["months"] == [] and body["busiest_days"] == [] and body["coverage"] == []


# ---- the day-by-day timeline ----

def test_a_timeline_lists_every_day_in_the_span_with_its_stories(api_client):
    days = api_client.get("/api/v1/news/timeline", params={"start": "2020-07-26", "end": "2020-07-28"}).json()

    assert [d["date"] for d in days] == ["2020-07-26", "2020-07-27", "2020-07-28"]
    assert days[0]["stories"] == [] and [s["id"] for s in days[1]["stories"]] == ["news-3", "news-1"]


def test_a_timeline_follows_the_county(api_client):
    days = api_client.get("/api/v1/news/timeline", params={"start": "2020-07-27", "end": "2020-07-27", "county": "cameron"}).json()

    assert [s["id"] for s in days[0]["stories"]] == ["news-3"]


@pytest.mark.parametrize("params", [
    {"start": "2020-07-28", "end": "2020-07-27"},
    {"start": "2020-01-01", "end": "2020-03-01"},  # longer than a month
    {"start": "not a date", "end": "2020-07-27"},
])
def test_a_bad_timeline_span_is_a_422(api_client, params):
    assert api_client.get("/api/v1/news/timeline", params=params).status_code == 422


# ---- also reported by ----

def add_copy(fixture_db, article_id, publisher, url):
    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        row = connection.execute("select * from news_articles where id = ?", (article_id,)).fetchone()
        columns = [d[1] for d in connection.execute("pragma table_info(news_articles)")]
        story = dict(zip(columns, row, strict=True)) | {"id": f"copy-of-{article_id}", "publisher": publisher, "source_url": url,
                                                        "article_id": article_id, "reason": "same_story"}
        connection.execute(f"insert into news_article_copies ({', '.join(story)}) values ({', '.join('?' * len(story))})", tuple(story.values()))


def test_a_story_lists_the_other_outlets_that_told_it(api_client, fixture_db):
    add_copy(fixture_db, "news-1", "ValleyCentral (KVEO, KGBT)", "https://vc.test/a")

    stories = {s["id"]: s for s in api_client.get("/api/v1/news").json()}

    assert stories["news-1"]["also_reported_by"] == [{"publisher": "ValleyCentral (KVEO, KGBT)", "source_url": "https://vc.test/a"}]
    assert stories["news-2"]["also_reported_by"] == []


def test_also_reported_by_reaches_the_event_and_the_timeline(api_client, fixture_db):
    add_copy(fixture_db, "news-1", "Border Report (Nexstar)", "https://br.test/a")

    context = api_client.get("/api/v1/events/noaa-storm-events-1/context").json()
    days = api_client.get("/api/v1/news/timeline", params={"start": "2020-07-27", "end": "2020-07-27"}).json()

    assert context["news"][0]["also_reported_by"][0]["publisher"] == "Border Report (Nexstar)"
    assert any(s["also_reported_by"] for s in days[0]["stories"])


def test_a_database_from_before_cleaning_has_no_copies_and_still_works(make_client, fixture_db):
    run(fixture_db, "drop table news_article_copies")

    stories = make_client(fixture_db).get("/api/v1/news").json()

    assert all(s["also_reported_by"] == [] for s in stories)
