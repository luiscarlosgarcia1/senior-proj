"""Pipeline: pipeline/build_news.py — collecting water-related stories into the news_articles table."""

import sqlite3
import threading
from collections import Counter
from contextlib import closing

import build_news
import pytest
from database import open_database, replace_table
from news_sources import Listing, Page


class FakeFetcher:
    """Serves '<html/>' for every URL and remembers what was asked for."""

    def __init__(self):
        self.requested = []
        self.stats = Counter()

    def get(self, url, *, limit=None, use_cache=True):
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

    rows, stats = build_news.collect([source], FakeFetcher(), retrieved_at="2026-10-23T12:00:00Z", since="2018-01-01")

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
    assert "flood" in row["topics"].split(",") and row["kind"] == "news" and row["headline_from"] == "page"
    assert set(row) == {
        "id", "publisher", "source_url", "headline", "published_at", "excerpt", "county", "counties", "city",
        "places", "matched_terms", "topics", "kind", "headline_from", "retrieved_at",
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


def test_limit_is_a_dry_run_that_writes_nothing(tmp_path):
    database = tmp_path / "db.sqlite3"
    build_news.main(database, sources=[FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})],
                    fetcher=FakeFetcher(), limit=5)

    assert not database.exists()


# ---- the wider crawl ----

NOW = "2026-11-09T12:00:00Z"


class ClosedSource:
    """A publisher whose pages refuse us: the address and day are all there is."""

    id = "news-closed"
    publisher = "Closed Channel"
    home_url = "https://closed.test"
    reads_pages = False
    local_sections = ("/news/local-news/",)
    kind = "news"
    needs_place_in_address = False

    def __init__(self, listings):
        self._listings = listings

    def listings(self, fetcher):
        yield from self._listings

    def page_from_listing(self, listing):
        words = listing.url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
        return Page(url=listing.url, headline=words, description="", published_at=listing.published)


def test_there_is_no_date_floor_by_default():
    assert build_news.NEWS_SINCE < "2000-01-01"
    source = FakeSource([listing("https://fake.test/news/flood-2005", published="2005-08-01T00:00:00Z")],
                        {"https://fake.test/news/flood-2005": page("https://fake.test/news/flood-2005", "Flooding in McAllen", published_at="2005-08-01T00:00:00Z")})

    rows, _ = build_news.collect([source], FakeFetcher(), retrieved_at=NOW)

    assert len(rows) == 1


def test_rows_carry_topics_and_a_story_about_the_whole_valley_has_no_county():
    url = "https://fake.test/news/rain-for-the-rgv"
    source = FakeSource([listing(url)], {url: page(url, "Heavy rain and street flooding soak the RGV")})

    (row,) = build_news.collect([source], FakeFetcher(), retrieved_at=NOW)[0]

    assert row["county"] is None and row["counties"] == "" and row["city"] is None
    assert {"flood", "rain"} <= set(row["topics"].split(","))


def test_official_sources_are_marked():
    url = "https://gov.test/news/boil-water-notice-edinburg"
    source = FakeSource([listing(url)], {url: page(url, "Boil water notice for Edinburg")})
    source.kind = "official"

    (row,) = build_news.collect([source], FakeFetcher(), retrieved_at=NOW)[0]

    assert row["kind"] == "official" and "water_system" in row["topics"]


def test_a_closed_publisher_is_never_asked_for_pages_and_its_headline_comes_from_the_address():
    fetcher = FakeFetcher()
    listings = [
        listing("https://closed.test/news/local-news/street-flooding-in-los-fresnos/", published="2020-07-24"),
        listing("https://closed.test/news/local-news/football-team-wins/", published="2020-07-24"),
    ]

    rows, stats = build_news.collect([ClosedSource(listings)], fetcher, retrieved_at=NOW)

    assert fetcher.requested == [] and len(rows) == 1
    assert rows[0]["headline_from"] == "address" and rows[0]["excerpt"] is None and rows[0]["county"] == "cameron"
    assert stats["news-closed"]["kept"] == 1 and stats["news-closed"]["slug_skipped"] == 1


def test_a_local_section_story_without_a_town_is_kept_as_a_valley_story_but_other_sections_are_not():
    listings = [
        listing("https://closed.test/news/local-news/heavy-rain-expected-overnight/", published="2020-07-24"),
        listing("https://closed.test/news/national-news/heavy-rain-expected-overnight-in-ohio/", published="2020-07-24"),
    ]

    rows, stats = build_news.collect([ClosedSource(listings)], FakeFetcher(), retrieved_at=NOW)

    assert [r["source_url"].split("/")[4] for r in rows] == ["local-news"] and rows[0]["county"] is None
    assert stats["news-closed"]["no_match"] == 1


def test_a_statewide_outlet_is_only_read_when_the_address_names_a_valley_place():
    fetcher = FakeFetcher()
    near = "https://state.test/2020/07/25/flooding-in-harlingen-after-storm"
    far = "https://state.test/2020/07/25/flooding-in-houston-after-storm"
    source = FakeSource([listing(near), listing(far)], {near: page(near, "Flooding in Harlingen after storm")})
    source.needs_place_in_address = True

    rows, stats = build_news.collect([source], fetcher, retrieved_at=NOW)

    assert fetcher.requested == [near] and len(rows) == 1
    assert stats["news-fake"]["not_valley_address"] == 1


def test_every_source_runs_at_the_same_time():
    """Sources must overlap: each one waits (briefly) for the other to start, which only works side by side."""
    both_started = threading.Barrier(2, timeout=3)

    class Rendezvous(FakeSource):
        def listings(self, fetcher):
            both_started.wait()
            yield from self._listings

    a = Rendezvous([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})
    other = "https://other.test/news/flooding-in-weslaco"
    b = Rendezvous([listing(other)], {other: page(other, "Flooding in Weslaco")})
    b.id, b.publisher = "news-other", "Other Gazette"

    rows, stats = build_news.collect([a, b], FakeFetcher(), retrieved_at=NOW)

    assert len(rows) == 2 and stats["news-fake"]["kept"] == 1 and stats["news-other"]["kept"] == 1


def test_a_source_that_crashes_is_counted_and_the_others_finish():
    class Crashes(FakeSource):
        def listings(self, fetcher):
            raise RuntimeError("a bug in one publisher's reader")
            yield  # pragma: no cover

    bad = Crashes([], {})
    bad.id = "news-bad"
    good = FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})

    rows, stats = build_news.collect([bad, good], FakeFetcher(), retrieved_at=NOW)

    assert len(rows) == 1 and stats["news-bad"]["error"] == 1


def test_a_stop_request_ends_the_crawl_cleanly():
    stop = threading.Event()
    stop.set()
    source = FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})

    rows, _ = build_news.collect([source], FakeFetcher(), retrieved_at=NOW, stop=stop)

    assert rows == []


def stored(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("select publisher, source_url from news_articles order by source_url").fetchall()


def test_a_publisher_that_gave_nothing_this_time_keeps_its_earlier_stories(tmp_path):
    database = tmp_path / "db.sqlite3"
    build_news.main(database, sources=[FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})], fetcher=FakeFetcher())
    down = FakeSource([], {}, broken=True)  # the same publisher, unreachable now
    fine = "https://fine.test/news/flooding-in-weslaco"
    working = FakeSource([listing(fine)], {fine: page(fine, "Flooding in Weslaco")})
    working.id, working.publisher = "news-fine", "Fine Gazette"

    build_news.main(database, sources=[down, working], fetcher=FakeFetcher())

    assert stored(database) == [("Fake Gazette", GOOD), ("Fine Gazette", fine)]


def test_running_only_some_sources_leaves_the_rest_in_place(tmp_path):
    database = tmp_path / "db.sqlite3"
    other = "https://other.test/news/flooding-in-weslaco"
    first = FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})
    second = FakeSource([listing(other)], {other: page(other, "Flooding in Weslaco")})
    second.id, second.publisher = "news-other", "Other Gazette"
    build_news.main(database, sources=[first, second], fetcher=FakeFetcher())

    build_news.main(database, sources=[first, second], fetcher=FakeFetcher(), only=["news-other"])

    assert stored(database) == [("Fake Gazette", GOOD), ("Other Gazette", other)]


def test_an_unknown_source_name_is_an_error(tmp_path):
    with pytest.raises(SystemExit, match="news-nope"):
        build_news.main(tmp_path / "db.sqlite3", sources=[FakeSource([], {})], fetcher=FakeFetcher(), only=["news-nope"])


def test_old_rows_from_before_the_new_columns_are_carried_over(tmp_path):
    database = tmp_path / "db.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:  # a table as the first version made it
        connection.execute("""CREATE TABLE news_articles (id TEXT PRIMARY KEY, publisher TEXT NOT NULL, source_url TEXT NOT NULL,
            headline TEXT NOT NULL, published_at TEXT NOT NULL, excerpt TEXT, county TEXT, counties TEXT NOT NULL, city TEXT,
            places TEXT, matched_terms TEXT NOT NULL, retrieved_at TEXT NOT NULL)""")
        connection.execute("INSERT INTO news_articles VALUES ('1','Old Gazette','https://old.test/a','Flooding closes streets in Edinburg','2019-01-01',NULL,'hidalgo','hidalgo',NULL,NULL,'flood','2026-10-23T00:00:00Z')")
    fine = "https://fine.test/news/flooding-in-weslaco"
    working = FakeSource([listing(fine)], {fine: page(fine, "Flooding in Weslaco")})

    build_news.main(database, sources=[working], fetcher=FakeFetcher())

    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("select topics, kind, headline_from from news_articles where id = '1'").fetchone()
    assert row == ("flood", "news", "page")  # old rows get sensible values for the new columns


def test_the_data_source_note_says_what_was_skipped_and_what_is_stored(tmp_path):
    database = tmp_path / "db.sqlite3"
    source = ClosedSource([listing("https://closed.test/news/local-news/street-flooding-in-los-fresnos/", published="2020-07-24")])

    build_news.main(database, sources=[source], fetcher=FakeFetcher())

    with closing(sqlite3.connect(database)) as connection:
        (notes,) = connection.execute("select notes from data_sources where id = 'news-closed'").fetchone()
    assert "made from the story's address" in notes and "no description is stored" in notes


def test_a_host_that_asked_us_to_come_back_later_is_named_at_the_end_of_the_run(tmp_path, capsys):
    class Waiting(FakeFetcher):
        def paused_hosts(self):
            return {"limited.test": 2700.0}

    source = FakeSource([listing(GOOD)], {GOOD: page(GOOD, "Flooding closes streets in McAllen")})

    build_news.main(tmp_path / "db.sqlite3", sources=[source], fetcher=Waiting())

    out = capsys.readouterr().out
    assert "limited.test" in out and "45 more minutes" in out and "run it again" in out


# ---- cleaning is part of the build ----

def outlet(source_id, publisher, listings, pages):
    source = FakeSource(listings, pages)
    source.id, source.publisher = source_id, publisher
    return source


def table(database, name):
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f"select * from {name} order by id")]


URL_A = "https://a.test/news/flooding-closes-streets-in-mcallen"
URL_B = "https://b.test/news/flooding-closes-streets-in-mcallen"


def two_outlets():
    a = outlet("news-a", "Outlet A", [listing(URL_A, "2020-07-26T12:00:00Z")],
               {URL_A: page(URL_A, "Flooding closes streets &amp; roads in McAllen", published_at="2020-07-26T12:00:00Z")})
    b = outlet("news-b", "Outlet B", [listing(URL_B, "2020-07-27T12:00:00Z")],
               {URL_B: page(URL_B, "Flooding closes streets & roads in McAllen", published_at="2020-07-27T12:00:00Z")})
    return a, b


def test_the_build_tidies_the_text_and_keeps_the_other_outlets_copy_as_a_copy(tmp_path):
    database = tmp_path / "db.sqlite3"

    build_news.main(database, sources=list(two_outlets()), fetcher=FakeFetcher())

    (kept,) = table(database, "news_articles")
    assert kept["publisher"] == "Outlet A" and kept["headline"] == "Flooding closes streets & roads in McAllen"
    (copy,) = table(database, "news_article_copies")
    assert copy["publisher"] == "Outlet B" and copy["article_id"] == kept["id"] and copy["source_url"] == URL_B


def test_a_story_that_fails_a_check_is_set_aside_with_its_reason_not_dropped(tmp_path):
    database = tmp_path / "db.sqlite3"
    future = outlet("news-c", "Outlet C", [listing(URL_A.replace("a.test", "c.test"), "2099-01-01T00:00:00Z")],
                    {URL_A.replace("a.test", "c.test"): page(URL_A.replace("a.test", "c.test"), "Flooding closes streets in McAllen", published_at="2099-01-01T00:00:00Z")})
    a, _ = two_outlets()

    build_news.main(database, sources=[a, future], fetcher=FakeFetcher())

    assert [row["publisher"] for row in table(database, "news_articles")] == ["Outlet A"]
    (rejected,) = table(database, "news_rejected")
    assert rejected["publisher"] == "Outlet C" and rejected["reason"] == "bad_date" and rejected["headline"] == "Flooding closes streets in McAllen"


def test_a_copy_whose_partner_is_gone_comes_back_as_a_story_on_the_next_partial_run(tmp_path):
    database = tmp_path / "db.sqlite3"
    a, b = two_outlets()
    build_news.main(database, sources=[a, b], fetcher=FakeFetcher())
    assert len(table(database, "news_article_copies")) == 1

    other = "https://a.test/news/drainage-project-begins-in-weslaco"
    a_now = outlet("news-a", "Outlet A", [listing(other, "2020-09-01T12:00:00Z")], {other: page(other, "Drainage project begins in Weslaco", published_at="2020-09-01T12:00:00Z")})
    build_news.main(database, sources=[a_now, b], only=["news-a"], fetcher=FakeFetcher())

    assert sorted(row["publisher"] for row in table(database, "news_articles")) == ["Outlet A", "Outlet B"]
    assert table(database, "news_article_copies") == []


def test_a_partial_run_keeps_what_was_set_aside_for_the_outlets_it_did_not_run(tmp_path):
    database = tmp_path / "db.sqlite3"
    a, b = two_outlets()
    build_news.main(database, sources=[a, b], fetcher=FakeFetcher())

    build_news.main(database, sources=[a, b], only=["news-a"], fetcher=FakeFetcher())

    (copy,) = table(database, "news_article_copies")
    assert copy["publisher"] == "Outlet B"
    assert [row["publisher"] for row in table(database, "news_articles")] == ["Outlet A"]


def test_stories_stored_by_an_earlier_build_are_cleaned_too(tmp_path):
    database = tmp_path / "db.sqlite3"
    old = {
        "id": "old1", "publisher": "Old Gazette", "source_url": "https://old.test/a", "headline": "Rio Grande City woman sentenced",
        "published_at": "2020-01-01T00:00:00Z", "excerpt": None, "county": "starr", "counties": "starr", "city": "Rio Grande City",
        "places": None, "matched_terms": "rio grande", "topics": "water_system", "kind": "news", "headline_from": "page",
        "retrieved_at": "2024-01-01T00:00:00Z",
    }
    with open_database(database) as connection:
        replace_table(connection, "news_articles", [old])
    a, _ = two_outlets()

    build_news.main(database, sources=[a], fetcher=FakeFetcher())

    assert [row["publisher"] for row in table(database, "news_articles")] == ["Outlet A"]
    (rejected,) = table(database, "news_rejected")
    assert rejected["id"] == "old1" and rejected["reason"] == "place_name_only"


def test_the_data_source_note_says_what_cleaning_removed(tmp_path):
    database = tmp_path / "db.sqlite3"
    a, b = two_outlets()
    future = outlet("news-c", "Outlet C", [listing("https://c.test/news/flooding-in-weslaco", "2099-01-01T00:00:00Z")],
                    {"https://c.test/news/flooding-in-weslaco": page("https://c.test/news/flooding-in-weslaco", "Flooding in Weslaco streets", published_at="2099-01-01T00:00:00Z")})

    build_news.main(database, sources=[a, b, future], fetcher=FakeFetcher())

    with closing(sqlite3.connect(database)) as connection:
        notes = dict(connection.execute("select id, notes from data_sources"))
    assert "1 merged into another outlet" in notes["news-b"] and "Cleaning removed nothing" in notes["news-a"]
    assert "1 rejected (1 bad_date)" in notes["news-c"]
