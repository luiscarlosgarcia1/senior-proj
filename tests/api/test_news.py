"""API: /api/v1/news and the news in an event's context."""

import sqlite3
from contextlib import closing


def test_news_lists_newest_first(api_client):
    stories = api_client.get("/api/v1/news").json()

    assert [s["id"] for s in stories] == ["news-1", "news-3", "news-2"]
    assert stories[0] == {
        "id": "news-1", "publisher": "KRGV Channel 5 News", "source_url": "https://example.test/news/news-1",
        "headline": "Flooding closes Weslaco streets", "published_at": "2020-07-27T14:03:00Z",
        "excerpt": "A short description.", "county": "hidalgo", "counties": ["hidalgo"], "city": "Weslaco",
        "places": None,
    }


def test_news_filtered_by_county(api_client):
    stories = api_client.get("/api/v1/news", params={"county": "cameron"}).json()

    assert [s["id"] for s in stories] == ["news-3"]


def test_news_county_includes_stories_that_name_it_second(api_client, fixture_db):
    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("update news_articles set counties = 'hidalgo,starr' where id = 'news-1'")

    stories = api_client.get("/api/v1/news", params={"county": "starr"}).json()

    assert [s["id"] for s in stories] == ["news-1"]


def test_news_filtered_by_year(api_client):
    stories = api_client.get("/api/v1/news", params={"year": 2018}).json()

    assert [s["id"] for s in stories] == ["news-2"]


def test_news_bad_county_422(api_client):
    assert api_client.get("/api/v1/news", params={"county": "texas"}).status_code == 422


def test_news_missing_table_is_an_empty_list(make_client, fixture_db):
    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("drop table news_articles")

    response = make_client(fixture_db).get("/api/v1/news")

    assert response.status_code == 200 and response.json() == []


def test_event_context_includes_news_in_the_window(api_client):
    context = api_client.get("/api/v1/events/noaa-storm-events-1/context").json()  # Hidalgo, 2020-07-25

    assert [s["id"] for s in context["news"]] == ["news-1"]  # 07-27 is inside +3 days; not the 2018 or Cameron stories


def test_event_context_news_window_excludes_before_and_after(api_client, fixture_db):
    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("update news_articles set published_at = '2020-07-23' where id = 'news-1'")  # two days before
    assert api_client.get("/api/v1/events/noaa-storm-events-1/context").json()["news"] == []

    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("update news_articles set published_at = '2020-07-29T23:59:00Z' where id = 'news-1'")  # +4 days
    assert api_client.get("/api/v1/events/noaa-storm-events-1/context").json()["news"] == []


def test_event_context_news_missing_table_is_empty(make_client, fixture_db):
    with closing(sqlite3.connect(fixture_db)) as connection, connection:
        connection.execute("drop table news_articles")

    context = make_client(fixture_db).get("/api/v1/events/noaa-storm-events-1/context").json()

    assert context["news"] == []
