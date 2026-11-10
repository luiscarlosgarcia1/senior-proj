"""Pipeline: pipeline/news_wayback.py — old Valley news from the Internet Archive's Wayback Machine.

The index answers and the archived pages here are small stand-ins with the shape of the real ones we looked
at: The Monitor's 2009 `articles/<words>-<id>-<words>.html` addresses (the page has a `publication_date`
meta tag and a title followed by its tags), and KRGV's 2005 `/2005/8/31/4232/<Headline>` addresses (the day is
in the address, the title ends in the station name).
"""

from collections import Counter
from urllib.parse import parse_qs, urlsplit

import build_news
import news_outlets
import pytest
from news_sources import Listing
from news_wayback import WaybackSource, parse_index, wayback_sources

MONITOR = "http://www.themonitor.com:80/articles/alamo-27894-body-canal.html"
MONITOR_FETCH = "https://web.archive.org/web/20090624205349id_/http://www.themonitor.com:80/articles/alamo-27894-body-canal.html"
MONITOR_CITE = "https://web.archive.org/web/20090624205349/http://www.themonitor.com/articles/alamo-27894-body-canal.html"
KRGV = "http://krgv.com:80/2005/8/31/4232/Valley-hurricane-relief-efforts"
KRGV_FETCH = "https://web.archive.org/web/20051023074451id_/http://krgv.com:80/2005/8/31/4232/Valley-hurricane-relief-efforts"

MONITOR_PAGE = (
    "<html><head><title>Man's body found in canal near Alamo | alamo, body, canal - Now - TheMonitor.com</title>"
    '<meta name="Description" content="Now: Man\'s body found in canal near Alamo | alamo, body, canal" />'
    '<meta name="publication_date" content="2009-06-23" /></head><body>…</body></html>'
)
KRGV_PAGE = "<html><head><title>Valley hurricane relief efforts - NEWSCHANNEL 5</title></head><body>Posted Wednesday, August 31, 2005</body></html>"


class FakeFetcher:
    """Answers the index with scripted pages and archived pages from a dict; remembers every request."""

    def __init__(self, index_pages, pages=None):
        self.index_pages, self.pages, self.requests = list(index_pages), pages or {}, []
        self.stats = Counter()

    def get(self, url, *, limit=None, use_cache=True):
        self.requests.append(url)
        if "/cdx/search/cdx" in url:
            return self.index_pages.pop(0).encode() if self.index_pages else None
        body = self.pages.get(url)
        if body is not None:
            self.stats["fetched"] += 1
        return body.encode() if isinstance(body, str) else body


def monitor_source(**options):
    return WaybackSource("news-wayback-themonitor", "The Monitor (via Wayback Machine)", "https://www.themonitor.com", "themonitor.com",
                         strip_title=r"\s*\|.*$", **options)


def query_of(url):
    return {key: values for key, values in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


# ---- reading the index ----

def test_parse_index_reads_rows_and_the_key_to_carry_on_from():
    rows, key = parse_index(f"{MONITOR} 20090624205349\n{KRGV} 20051023074451\n\ncom%2Cthemonitor%29%2Farticles%2Fz 20090701000000\n")

    assert rows == [(MONITOR, "20090624205349"), (KRGV, "20051023074451")]
    assert key == "com%2Cthemonitor%29%2Farticles%2Fz 20090701000000"


def test_parse_index_without_a_key_is_the_last_page():
    rows, key = parse_index(f"{MONITOR} 20090624205349\n")

    assert rows == [(MONITOR, "20090624205349")] and key is None


def test_parse_index_ignores_lines_that_are_not_rows():
    assert parse_index("garbage\n\n") == ([], None)
    assert parse_index("") == ([], None)


# ---- listing ----

def test_the_index_is_asked_for_pages_that_loaded_and_have_a_water_word_in_the_address():
    fetcher = FakeFetcher([f"{MONITOR} 20090624205349\n"])

    list(monitor_source().listings(fetcher))

    query = query_of(fetcher.requests[0])
    assert urlsplit(fetcher.requests[0]).netloc == "web.archive.org" and urlsplit(fetcher.requests[0]).path == "/cdx/search/cdx"
    assert query["url"] == ["themonitor.com/*"] and query["collapse"] == ["urlkey"]  # the first capture of each address
    assert "statuscode:200" in query["filter"] and "mimetype:text/html" in query["filter"]
    water = next(f for f in query["filter"] if f.startswith("original:"))
    assert "(?i)" in water and "flood" in water and "hurricane" in water and "canal" in water and "agua" in water
    assert query["showResumeKey"] == ["true"] and "to" not in query


def test_captures_after_the_cutoff_are_not_asked_for():
    fetcher = FakeFetcher([""])

    list(monitor_source(until="2016-12-31").listings(fetcher))

    assert query_of(fetcher.requests[0])["to"] == ["20161231"]


def test_each_row_becomes_a_listing_that_fetches_the_archived_copy_without_the_archive_banner():
    fetcher = FakeFetcher([f"{MONITOR} 20090624205349\n"])

    (listing,) = list(monitor_source().listings(fetcher))

    assert listing.url == MONITOR_FETCH  # id_ is the page as the publisher served it
    assert listing.title == "Alamo 27894 Body Canal"  # the prefilter reads the words of the address
    assert listing.published is None  # this address has no day in it


def test_a_day_in_the_address_is_the_listings_date():
    fetcher = FakeFetcher([f"{KRGV} 20051023074451\n"])

    (listing,) = list(WaybackSource("news-wayback-krgv", "K", "https://krgv.com", "krgv.com").listings(fetcher))

    assert listing.published == "2005-08-31"


def test_addresses_with_a_query_and_pictures_are_left_out():
    rows = "\n".join((
        f"{MONITOR}?wap=1 20090630004558",
        f"{MONITOR}?plckFindCommentKey=CommentKey:0663dc20 20101213083000",
        "http://www.valleymorningstar.com/articles/cola_3940___article.html/1180098278-cocacolavitaminwater.jpg 20071030053105",
        f"{MONITOR} 20090624205349",
    ))
    fetcher = FakeFetcher([rows + "\n"])

    listings = list(monitor_source().listings(fetcher))

    assert [listing.url for listing in listings] == [MONITOR_FETCH]


def test_one_story_under_two_old_address_forms_is_listed_once():
    first = "http://www.themonitor.com:80/articles/authorities_8878___article.html/canal_bodies.html"
    second = "http://www.themonitor.com/articles/authorities_8878___article.html/other_words.html"
    fetcher = FakeFetcher([f"{first} 20080211102157\n{second} 20080301000000\n"])

    listings = list(monitor_source().listings(fetcher))

    assert len(listings) == 1 and "20080211102157" in listings[0].url


def test_www_and_the_port_do_not_make_a_second_story():
    fetcher = FakeFetcher([f"{MONITOR} 20090624205349\nhttp://themonitor.com/articles/alamo-27894-body-canal.html 20090701000000\n"])

    assert len(list(monitor_source().listings(fetcher))) == 1


def test_a_long_index_is_read_page_by_page_with_the_key_the_archive_hands_back():
    first = f"{MONITOR} 20090624205349\n\ncom%2Cthemonitor%29%2Farticles%2Fm+20090701000000\n"
    second = "http://www.themonitor.com/articles/benito-57907-san-water.html 20120113211856\n"
    fetcher = FakeFetcher([first, second])

    listings = list(monitor_source().listings(fetcher))

    assert len(listings) == 2 and len(fetcher.requests) == 2
    assert "resumeKey=com%2Cthemonitor%29%2Farticles%2Fm+20090701000000" in fetcher.requests[1]
    assert "resumeKey" not in fetcher.requests[0]


def test_an_index_that_cannot_be_fetched_lists_nothing():
    assert list(monitor_source().listings(FakeFetcher([]))) == []


# ---- reading an archived page ----

def test_a_page_gives_its_headline_without_the_tag_list_and_its_own_publication_date():
    listing = Listing(url=MONITOR_FETCH, published=None, title="Alamo 27894 Body Canal")

    page = monitor_source().parse(MONITOR_FETCH, MONITOR_PAGE, listing)

    assert page.headline == "Man's body found in canal near Alamo"
    assert page.published_at == "2009-06-23T00:00:00Z"
    assert page.url == MONITOR_CITE  # the link works even though the publisher's address does not


def test_no_description_is_kept_because_old_pages_fill_it_with_the_headline_and_tags():
    listing = Listing(url=MONITOR_FETCH, published=None, title=None)

    assert monitor_source().parse(MONITOR_FETCH, MONITOR_PAGE, listing).description == ""


def test_the_day_in_the_address_dates_a_page_that_has_none_of_its_own():
    source = WaybackSource("news-wayback-krgv", "KRGV", "https://krgv.com", "krgv.com", strip_title=r"\s+-\s+NEWSCHANNEL 5$")
    listing = Listing(url=KRGV_FETCH, published="2005-08-31", title="Valley Hurricane Relief Efforts")

    page = source.parse(KRGV_FETCH, KRGV_PAGE, listing)

    assert page.headline == "Valley hurricane relief efforts" and page.published_at == "2005-08-31T00:00:00Z"
    assert page.url == "https://web.archive.org/web/20051023074451/http://krgv.com/2005/8/31/4232/Valley-hurricane-relief-efforts"


def test_a_page_whose_title_is_only_the_station_name_has_no_headline_and_is_skipped():
    source = next(source for source in wayback_sources() if source.id == "news-wayback-krgv")
    listing = Listing(url=KRGV_FETCH, published="2005-05-17", title="Hurricane Season")

    assert source.parse(KRGV_FETCH, "<html><head><title>NEWSCHANNEL 5</title></head></html>", listing) is None
    assert source.parse(KRGV_FETCH, KRGV_PAGE, listing).headline == "Valley hurricane relief efforts"


@pytest.mark.parametrize("title", [
    "Mexico falling behind on water deliveries - The Monitor",
    "Mexico falling behind on water deliveries | water, mexico - Now - TheMonitor.com",
    "Mexico falling behind on water deliveries - News - Valley Morning Star",
])
def test_the_papers_names_and_tag_lists_are_cut_from_the_end_of_a_title(title):
    from news_wayback import PAPER_TITLE_TAIL

    source = WaybackSource("news-wayback-x", "X", "https://x.test", "x.test", strip_title=PAPER_TITLE_TAIL)
    listing = Listing(url=MONITOR_FETCH, published="2009-06-23", title=None)

    page = source.parse(MONITOR_FETCH, f"<html><head><title>{title}</title></head></html>", listing)

    assert page.headline == "Mexico falling behind on water deliveries"


def test_a_page_with_no_date_anywhere_is_not_dated_by_when_it_was_archived():
    listing = Listing(url=MONITOR_FETCH, published=None, title=None)

    assert monitor_source().parse(MONITOR_FETCH, "<html><head><title>Canal flooding in Alamo</title></head></html>", listing) is None


def test_a_page_with_no_title_is_skipped():
    listing = Listing(url=MONITOR_FETCH, published="2009-06-23", title=None)

    assert monitor_source().parse(MONITOR_FETCH, "<html><head></head><body>x</body></html>", listing) is None


# ---- inside a build ----

def test_a_build_keeps_an_archived_story_that_names_a_valley_place_and_cites_the_archive(tmp_path):
    fetcher = FakeFetcher([f"{MONITOR} 20090624205349\nhttp://www.themonitor.com/articles/brain-38991-addiction-circuits.html 20100527234328\n"],
                          {MONITOR_FETCH: MONITOR_PAGE})

    rows, stats = build_news.collect([monitor_source()], fetcher, retrieved_at="2026-11-09T00:00:00Z")

    (row,) = rows
    assert row["source_url"] == MONITOR_CITE and row["publisher"] == "The Monitor (via Wayback Machine)"
    assert row["published_at"] == "2009-06-23T00:00:00Z" and row["city"] == "Alamo" and row["county"] == "hidalgo"
    assert row["headline_from"] == "page" and row["excerpt"] is None and "water_system" in row["topics"]
    counts = stats["news-wayback-themonitor"]
    assert counts["listed"] == 2 and counts["slug_skipped"] == 1 and counts["kept"] == 1  # "Brain" is not "rain"
    assert len(fetcher.requests) == 2  # the index, and the one page worth reading


def test_the_data_source_note_says_the_copies_are_from_the_wayback_machine(tmp_path):
    import sqlite3
    from contextlib import closing

    database = tmp_path / "db.sqlite3"
    fetcher = FakeFetcher([f"{MONITOR} 20090624205349\n"], {MONITOR_FETCH: MONITOR_PAGE})

    build_news.main(database, sources=[monitor_source()], fetcher=fetcher)

    with closing(sqlite3.connect(database)) as connection:
        (notes,) = connection.execute("select notes from data_sources where id = 'news-wayback-themonitor'").fetchone()
    assert "Wayback Machine" in notes and "publication date" in notes


# ---- the roster ----

def test_the_roster_has_the_old_valley_papers_each_with_its_own_publisher_name():
    sources = wayback_sources()

    assert {source.id for source in sources} >= {
        "news-wayback-themonitor", "news-wayback-brownsvilleherald", "news-wayback-valleymorningstar", "news-wayback-krgv",
    }
    publishers = [source.publisher for source in sources]
    assert len(set(publishers)) == len(publishers) and all("Wayback Machine" in publisher for publisher in publishers)
    # a different name from the live source's, so each source's earlier rows are kept or replaced on their own
    live = {source.publisher for source in news_outlets.default_sources() if not source.id.startswith("news-wayback")}
    assert not live & set(publishers)


def test_the_build_roster_includes_them_with_unique_ids():
    ids = [source.id for source in news_outlets.default_sources()]

    assert len(ids) == len(set(ids)) and "news-wayback-krgv" in ids


def test_each_site_is_cut_off_where_its_live_sitemaps_begin_so_no_story_is_listed_twice():
    until = {source.id: source.until for source in wayback_sources()}

    assert until["news-wayback-krgv"] == "2016-12-31"  # the live KRGV sitemaps cover the new site
    # myrgv.com's sitemaps begin in 2016; these domains kept being copied into 2019, with 2017 stories myrgv.com already lists
    assert until["news-wayback-themonitor"] == until["news-wayback-brownsvilleherald"] == until["news-wayback-valleymorningstar"] == "2015-12-31"


@pytest.mark.parametrize("source", wayback_sources(), ids=lambda source: source.id)
def test_every_wayback_source_is_slow_and_honest_about_what_it_is(source):
    assert source.reads_pages and source.kind == "news"
    assert "Wayback Machine" in source.about and "publication date" in source.about
