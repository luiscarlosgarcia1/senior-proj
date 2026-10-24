"""Pipeline: pipeline/build_news.py — collecting flood stories into the news_articles table."""

import sqlite3
from collections import Counter
from contextlib import closing

import build_news
import pytest
from news_sources import Listing, Page


class FakeFetcher:
    """Serves '<html/>' for every URL and remembers what was asked for."""

    def __init__(self):
        self.requested = []
        self.stats = Counter()

    def get(self, url):
        self.requested.append(url)
        self.stats["fetched"] += 1
        return b"<html/>"


class FakeSource:
    id = "news-fake"
    publisher = "Fake Gazette"
    home_url = "https://fake.test"

    def __init__(self, listings, pages, *, broken=False):
        self._listings, self._pages, self._broken = listings, pages, broken

    def listings(self, fetcher):
        if self._broken:
            raise OSError("down")
        yield from self._listings

    def parse(self, url, html, listing):
        return self._pages.get(url)


def page(url, headline, description="", published_at="2020-07-26T12:00:00Z"):
    return Page(url=url, headline=headline, description=description, published_at=published_at)


def listing(url, published="2020-07-26T12:00:00Z", title=None):
    return Listing(url=url, published=published, title=title)


GOOD = "https://fake.test/news/flooding-closes-streets-in-mcallen"


def test_collect_keeps_matching_stories_and_counts_the_rest():
    pages = {
        GOOD: page(GOOD, "Flooding closes streets in McAllen"),
        "https://fake.test/news/flood-budget": page("https://fake.test/news/flood-budget", "Flood budget talks continue"),  # no place
        "https://fake.test/news/flood-paywalled": None,  # parse() refuses it
    }
    source = FakeSource([
        listing(GOOD),
        listing("https://fake.test/news/flood-budget"),
        listing("https://fake.test/news/flood-paywalled"),
        listing("https://fake.test/news/flood-2017", published="2017-08-01T00:00:00Z"),
        listing("https://fake.test/news/city-council-meets"),  # no flood term in the slug
    ], pages)

    rows, stats = build_news.collect([source], FakeFetcher(), retrieved_at="2026-10-23T12:00:00Z")

    assert [r["source_url"] for r in rows] == [GOOD]
    assert stats["news-fake"] == Counter(
        listed=5, before_since=1, slug_skipped=1, fetched=3, unparsed=1, no_match=1, kept=1
    )


def test_same_story_at_two_urls_is_one_row():
    other = "http://fake.test/news/flooding-closes-streets-in-mcallen?utm_source=x"
    source = FakeSource([listing(GOOD), listing(other)], {GOOD: page(GOOD, "Flooding closes streets in McAllen"), other: page(other, "Flooding closes streets in McAllen")})

    rows, _ = build_news.collect([source], FakeFetcher(), retrieved_at="2026-10-23T12:00:00Z")

    assert len(rows) == 1


def test_slug_prefilter_avoids_the_fetch():
    fetcher = FakeFetcher()
    source = FakeSource([listing("https://fake.test/news/city-council-meets")], {})

    build_news.collect([source], fetcher, retrieved_at="2026-10-23T12:00:00Z")

    assert fetcher.requested == []


def test_listing_title_is_used_for_the_prefilter_when_there_is_one():
    url = "https://fake.test/news/a1234"  # a slug that says nothing
    fetcher = FakeFetcher()
    source = FakeSource([listing(url, title="Flooding closes streets in McAllen")], {url: page(url, "Flooding closes streets in McAllen")})

    rows, _ = build_news.collect([source], fetcher, retrieved_at="2026-10-23T12:00:00Z")

    assert len(rows) == 1


def test_news_row_fields():
    story = page(GOOD, "Flooding closes streets in McAllen", "Water covered Expressway 83 near Ware Road in Hidalgo County.")
    match = build_news.match_story(story.headline, story.description)

    row = build_news.news_row("Fake Gazette", story, match, "2026-10-23T12:00:00Z")

    assert row["publisher"] == "Fake Gazette"
    assert row["county"] == "hidalgo" and row["counties"] == "hidalgo"
    assert row["city"] == "McAllen"
    assert "Expressway 83" in row["places"] and "Ware Road" in row["places"]
    assert row["published_at"] == "2020-07-26T12:00:00Z"
    assert len(row["id"]) == 16
    assert set(row) == {
        "id", "publisher", "source_url", "headline", "published_at", "excerpt", "county", "counties", "city",
        "places", "matched_terms", "retrieved_at",
    }


def test_excerpt_is_capped_without_cutting_a_word():
    long = "flooded " * 80

    excerpt = build_news.excerpt_of(long)

    assert len(excerpt) <= build_news.EXCERPT_LIMIT
    assert excerpt.endswith("…") and not excerpt.endswith(" …")
    assert build_news.excerpt_of("  ") is None
    assert build_news.excerpt_of("Short.") == "Short."


def test_main_writes_table_and_source_rows(tmp_path):
    source = FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})
    database = tmp_path / "db.sqlite3"

    build_news.main(database, sources=[source], fetcher=FakeFetcher())

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("select source_url, county from news_articles").fetchall() == [(GOOD, "hidalgo")]
        sources = connection.execute("select id, publisher, record_count from data_sources").fetchall()
    assert sources == [("news-fake", "Fake Gazette", 1)]


def test_unreachable_source_is_skipped_and_others_load(tmp_path):
    working = FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})
    broken = FakeSource([], {}, broken=True)
    broken.id = "news-broken"
    database = tmp_path / "db.sqlite3"

    build_news.main(database, sources=[broken, working], fetcher=FakeFetcher())

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("select count(*) from news_articles").fetchone()[0] == 1


def test_no_rows_anywhere_keeps_the_old_table(tmp_path):
    database = tmp_path / "db.sqlite3"
    build_news.main(database, sources=[FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})], fetcher=FakeFetcher())

    with pytest.raises(SystemExit):
        build_news.main(database, sources=[FakeSource([], {}, broken=True)], fetcher=FakeFetcher())

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("select count(*) from news_articles").fetchone()[0] == 1


def test_limit_stops_after_that_many_fetches():
    urls = [f"https://fake.test/news/flood-story-{n}" for n in range(5)]
    source = FakeSource([listing(u) for u in urls], {})
    fetcher = FakeFetcher()

    build_news.collect([source], fetcher, retrieved_at="2026-10-23T12:00:00Z", limit=2)

    assert len(fetcher.requested) == 2


def test_decode_page_handles_windows_1252_pages():
    assert build_news.decode_page("Inundación".encode()) == "Inundación"
    assert build_news.decode_page(b"High School\x92s Flooding Issues") == "High School\u2019s Flooding Issues"
