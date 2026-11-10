"""Pipeline: pipeline/news_outlets.py — the other Valley publishers, read through their sitemaps.

The sitemaps and pages here are small stand-ins with the same shape as the real ones we looked at
(WordPress core and Yoast sitemap indexes, Nexstar's one-sitemap-a-day addresses, Texas Public Radio's
month files, Rio Grande Guardian's single sitemap).
"""

from datetime import date

import pytest
from news_outlets import (
    MonthlySitemapSource,
    NexstarDailySource,
    SitemapSource,
    date_in_url,
    default_sources,
)
from news_sources import Listing

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*entries):
    body = "".join(f"<url><loc>{loc}</loc>{'<lastmod>' + mod + '</lastmod>' if mod else ''}</url>" for loc, mod in entries)
    return f'<?xml version="1.0"?><urlset {NS}>{body}</urlset>'.encode()


def index(*children):
    return f'<?xml version="1.0"?><sitemapindex {NS}>{"".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)}</sitemapindex>'.encode()


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, *, limit=None, use_cache=True):
        self.calls.append((url, use_cache))
        return self.pages.get(url)


@pytest.mark.parametrize("url, expected", [
    ("https://x.test/featured/2021/01/12/story/", "2021-01-12"),
    ("https://www.tpr.org/show/texas-matters/2015-07-10/beyond-the-ice-bucket", "2015-07-10"),
    ("https://x.test/stories/peterson-visits-rgv,6491", None),
    ("https://x.test/uncategorized/0200/12/15/x/", None),
    ("https://x.test/2021/13/45/x/", None),
    ("http://krgv.com:80/2005/8/31/4232/Valley-hurricane-relief-efforts", "2005-08-31"),  # KRGV's old addresses: no zero padding
    ("https://x.test/2021/1/5/story/", "2021-01-05"),
    ("https://x.test/2018/12/345/x", None),
])
def test_date_in_url(url, expected):
    assert date_in_url(url) == expected


# ---- walking sitemaps ----

def test_a_sitemap_index_is_followed_into_the_wanted_children_only():
    pages = {
        "https://s.test/wp-sitemap.xml": index("https://s.test/post-sitemap1.xml", "https://s.test/page-sitemap.xml", "https://s.test/video-sitemap3.xml"),
        "https://s.test/post-sitemap1.xml": urlset(("https://s.test/2020/07/25/flood-hits-weslaco/", "2020-07-26T00:00:00+00:00")),
        "https://s.test/page-sitemap.xml": urlset(("https://s.test/about/", None)),
        "https://s.test/video-sitemap3.xml": urlset(("https://s.test/video/1/", None)),
    }
    fetcher = FakeFetcher(pages)
    source = SitemapSource("news-s", "S", "https://s.test", ["https://s.test/wp-sitemap.xml"], include=r"post-sitemap\d*\.xml$", exclude="video")

    listings = list(source.listings(fetcher))

    assert [listing.url for listing in listings] == ["https://s.test/2020/07/25/flood-hits-weslaco/"]
    assert [url for url, _ in fetcher.calls] == ["https://s.test/wp-sitemap.xml", "https://s.test/post-sitemap1.xml"]


def test_a_sitemap_that_is_already_a_list_of_stories_works_and_url_filter_picks_stories():
    fetcher = FakeFetcher({"https://s.test/all.xml": urlset(
        ("https://s.test/stories/peterson-visits-rgv,6491", "2006-10-17"),
        ("https://s.test/premium/travel-news/", "2025-08-14"),
    )})
    source = SitemapSource("news-s", "S", "https://s.test", ["https://s.test/all.xml"], url_filter=r"/stories/")

    (listing,) = list(source.listings(fetcher))

    assert listing.url.endswith("rgv,6491") and listing.published == "2006-10-17"  # the sitemap's date, as a fallback


def test_the_listing_date_prefers_the_address_then_a_news_date_then_lastmod():
    news = (
        f'<urlset {NS} xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url><loc>https://s.test/a</loc>'
        "<news:news><news:publication_date>2018-12-10T06:48:06-06:00</news:publication_date><news:title>Rain!</news:title></news:news>"
        "<lastmod>2019-01-01</lastmod></url></urlset>"
    ).encode()
    fetcher = FakeFetcher({"https://s.test/news.xml": news, "https://s.test/2020/05/05.xml": urlset(("https://s.test/2020/05/05/x/", "2021-01-01"))})

    (with_news,) = SitemapSource("n", "S", "https://s.test", ["https://s.test/news.xml"]).listings(fetcher)
    (from_url,) = SitemapSource("n", "S", "https://s.test", ["https://s.test/2020/05/05.xml"]).listings(fetcher)

    assert (with_news.published, with_news.title) == ("2018-12-10T12:48:06Z", "Rain!")
    assert from_url.published == "2020-05-05"


def test_one_broken_or_missing_sitemap_does_not_stop_the_rest():
    pages = {
        "https://s.test/index.xml": index("https://s.test/a.xml", "https://s.test/b.xml", "https://s.test/c.xml"),
        "https://s.test/a.xml": b"<not xml",
        "https://s.test/c.xml": urlset(("https://s.test/2020/01/01/ok/", None)),
    }  # b.xml is missing
    source = SitemapSource("n", "S", "https://s.test", ["https://s.test/index.xml"])

    assert [listing.url for listing in source.listings(FakeFetcher(pages))] == ["https://s.test/2020/01/01/ok/"]


def test_a_story_listed_twice_is_listed_once():
    fetcher = FakeFetcher({"https://s.test/a.xml": urlset(("https://s.test/x/", None), ("https://s.test/x/", None))})

    assert len(list(SitemapSource("n", "S", "https://s.test", ["https://s.test/a.xml"]).listings(fetcher))) == 1


def test_sitemap_nesting_is_bounded():
    pages = {"https://s.test/loop.xml": index("https://s.test/loop.xml")}  # an index that lists itself

    assert list(SitemapSource("n", "S", "https://s.test", ["https://s.test/loop.xml"]).listings(FakeFetcher(pages))) == []


# ---- reading a page ----

def page(head, body=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def read(html, published="2020-01-01", url="https://s.test/a"):
    source = SitemapSource("n", "S", "https://s.test", [])
    return source.parse(url, html, Listing(url, published, None))


def test_a_page_gives_headline_description_and_its_own_time():
    result = read(page(
        '<meta property="og:title" content="Flood plan: IBWC study"><meta property="og:description" content="MERCEDES — A new model [&hellip;]">'
        '<meta property="article:published_time" content="2019-02-19T03:46:44+00:00">'))

    assert result.headline == "Flood plan: IBWC study"
    assert result.description == "MERCEDES — A new model…"
    assert result.published_at == "2019-02-19T03:46:44Z"


def test_the_date_can_come_from_structured_data_or_a_time_tag():
    ld = page('<meta property="og:title" content="T"><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2012-04-26T10:00:00-05:00"}</script>')
    tag = page('<meta property="og:title" content="T">', '<time datetime="2013-05-06T07:08:09Z">May 6</time>')

    assert read(ld, published=None).published_at == "2012-04-26T15:00:00Z"
    assert read(tag, published=None).published_at == "2013-05-06T07:08:09Z"


def test_without_a_date_on_the_page_the_listing_date_is_used_and_without_either_it_is_skipped():
    html = page('<meta property="og:title" content="T">')

    assert read(html, published="2014-03-03").published_at == "2014-03-03"
    assert read(html, published=None) is None


def test_the_title_tag_is_the_fallback_headline_and_a_paywalled_page_is_skipped():
    assert read(page("<title>Only a title</title>")).headline == "Only a title"
    assert read(page('<meta property="og:title" content="T"><script>{"isAccessibleForFree": false}</script>')) is None
    assert read(page("")) is None


# ---- Nexstar: one sitemap a day, pages we are not let into ----

def nexstar(today, first=date(2020, 7, 24), **options):
    return NexstarDailySource("news-vc", "ValleyCentral", "https://vc.test", "vc.test", first, today=lambda: today, **options)


def test_every_day_has_its_own_sitemap_address_and_stories_are_dated_by_that_day():
    fetcher = FakeFetcher({
        "https://vc.test/sitemap.xml?yyyy=2020&mm=07&dd=24": urlset(("https://vc.test/news/local-news/flooding-in-weslaco/", "2020-07-24T10:00:00+00:00")),
        "https://vc.test/sitemap.xml?yyyy=2020&mm=07&dd=26": urlset(("https://vc.test/weather/rain-totals/", None)),
    })

    listings = list(nexstar(date(2020, 7, 26)).listings(fetcher))

    assert [(l.url.rsplit("/", 2)[1], l.published) for l in listings] == [("flooding-in-weslaco", "2020-07-24"), ("rain-totals", "2020-07-26")]
    assert len(fetcher.calls) == 3  # July 25 has no sitemap: asked about, nothing to read


def test_the_last_two_days_are_never_taken_from_the_cache():
    fetcher = FakeFetcher({})

    list(nexstar(date(2020, 7, 27)).listings(fetcher))

    assert dict(fetcher.calls) == {
        "https://vc.test/sitemap.xml?yyyy=2020&mm=07&dd=24": True,
        "https://vc.test/sitemap.xml?yyyy=2020&mm=07&dd=25": True,
        "https://vc.test/sitemap.xml?yyyy=2020&mm=07&dd=26": False,
        "https://vc.test/sitemap.xml?yyyy=2020&mm=07&dd=27": False,
    }


def test_these_pages_are_not_read_so_the_address_stands_in_for_the_headline():
    source = nexstar(date(2020, 7, 24))

    assert source.reads_pages is False
    made = source.page_from_listing(Listing("https://vc.test/news/local-news/street-flooding-in-los-fresnos/", "2020-07-24", None))

    assert (made.headline, made.description, made.published_at) == ("Street Flooding In Los Fresnos", "", "2020-07-24")
    assert source.page_from_listing(Listing("https://vc.test/news/local-news/", "2020-07-24", None)) is None  # a section page


# ---- Texas Public Radio: one file a month ----

def test_monthly_sitemaps_run_from_the_first_month_to_this_one():
    fetcher = FakeFetcher({"https://t.test/sitemap-200402.xml": urlset(("https://t.test/news/2004-02-03/flood-story", None))})
    source = MonthlySitemapSource("news-t", "T", "https://t.test", "https://t.test/sitemap-{yyyy}{mm}.xml", (2004, 1), today=lambda: date(2004, 3, 9))

    listings = list(source.listings(fetcher))

    assert [url for url, _ in fetcher.calls] == ["https://t.test/sitemap-200401.xml", "https://t.test/sitemap-200402.xml", "https://t.test/sitemap-200403.xml"]
    assert [l.published for l in listings] == ["2004-02-03"]


# ---- the roster ----

def test_the_roster():
    sources = default_sources()
    by_id = {s.id: s for s in sources}

    assert len(by_id) == len(sources)  # every id once
    assert {"news-krgv", "news-myrgv", "news-valleycentral", "news-borderreport", "news-foxrgv", "news-riograndeguardian",
            "news-progresstimes", "news-pispp", "news-tpr", "news-texastribune", "news-elperiodicousa"} <= set(by_id)
    assert by_id["news-valleycentral"].reads_pages is False and by_id["news-valleycentral"].local_sections
    assert all(by_id[i].needs_place_in_address for i in ("news-borderreport", "news-tpr", "news-texastribune"))
    assert not any(by_id[i].needs_place_in_address for i in ("news-krgv", "news-myrgv", "news-foxrgv", "news-riograndeguardian"))
    assert {s.kind for s in sources} == {"news", "official"} and by_id["official-ibwc"].kind == "official"
    for source in sources:
        assert source.home_url.startswith("https://") and source.publisher
