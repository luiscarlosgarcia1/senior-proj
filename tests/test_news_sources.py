"""Pipeline: pipeline/news_sources.py — what each publisher's sitemaps and pages give us.

The fixtures in tests/fixtures/news/ are trimmed copies of KRGV's real sitemap
index, one real news sitemap and one real article head (fetched 2026-10-23); the
paywalled page is synthetic.
"""

from pathlib import Path

from news_sources import KrgvSource, Listing, MyrgvSource

FIXTURES = Path(__file__).parent / "fixtures" / "news"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return self.pages.get(url)


def krgv_fetcher():
    news = fixture("krgv-sitemap-news-1.xml")
    return FakeFetcher({
        "https://www.krgv.com/sitemap.xml": fixture("krgv-sitemap-index.xml"),
        "http://www.krgv.com/sitemaps/sitemap-news-current.xml": news,
        "https://www.krgv.com/sitemaps/sitemap-news-1.xml": news,
    })


def test_listings_follow_news_sitemaps_only():
    fetcher = krgv_fetcher()

    listings = list(KrgvSource().listings(fetcher))

    assert not any("videos" in url or "categories" in url for url in fetcher.requested)
    assert len(listings) == 3  # the news pages hold the same three entries; each is listed once
    assert listings[0].url.startswith("https://www.krgv.com/news/")


def test_listing_carries_the_sitemaps_title_and_utc_date():
    listings = {listing.url.rsplit("/", 1)[1]: listing for listing in KrgvSource().listings(krgv_fetcher())}

    pharr = listings["city-of-pharr-prevents-future-flooding-with-trash-pick-up-event"]
    assert pharr.title == "City of Pharr Prevents Future Flooding with Trash Pick-Up Event"
    assert pharr.published == "2018-11-03T23:15:07Z"  # 17:15 at UTC-6


def test_parse_reads_headline_and_description_and_takes_the_date_from_the_listing():
    listing = Listing("https://www.krgv.com/news/pharr", "2018-11-03T23:15:07Z", "ignored")

    page = KrgvSource().parse(listing.url, fixture("krgv-article.html").decode(), listing)

    assert page.headline == "City of Pharr Prevents Future Flooding with Trash Pick-Up Event"
    assert page.description.startswith("In June, the city of Pharr saw more than 10 inches of rain")
    assert page.published_at == "2018-11-03T23:15:07Z"  # the page's own <meta name=Date> is the crawl day, not the story's


def test_parse_skips_paywalled_page():
    listing = Listing("https://www.krgv.com/news/x", "2019-01-01T00:00:00Z", None)

    assert KrgvSource().parse(listing.url, fixture("krgv-article-paywalled.html").decode(), listing) is None


def test_parse_skips_listing_without_a_date():
    listing = Listing("https://www.krgv.com/news/x", None, None)

    assert KrgvSource().parse(listing.url, fixture("krgv-article.html").decode(), listing) is None


def test_parse_skips_page_without_headline():
    listing = Listing("https://www.krgv.com/news/x", "2019-01-01T00:00:00Z", None)

    assert KrgvSource().parse(listing.url, "<html><head></head><body>nothing</body></html>", listing) is None


# ---- myrgv.com (The Monitor, Brownsville Herald, Valley Morning Star) ----
# Fixtures: trimmed copies of myrgv.com's real WordPress sitemaps and one real
# article head (fetched 2026-10-23), plus one hand-made URL with a bad date.

def myrgv_fetcher():
    return FakeFetcher({
        "https://myrgv.com/wp-sitemap.xml": fixture("myrgv-sitemap-index.xml"),
        "https://myrgv.com/wp-sitemap-posts-post-1.xml": fixture("myrgv-sitemap-posts-1.xml"),
    })


def test_myrgv_listings_read_post_sitemaps_only_and_date_from_the_url():
    fetcher = myrgv_fetcher()

    listings = list(MyrgvSource().listings(fetcher))

    assert not any("posts-page" in url or "taxonomies" in url for url in fetcher.requested)
    assert [listing.url for listing in listings] == [
        "https://myrgv.com/featured/2021/01/12/tough-year-tight-state-revenues-pose-challenge-for-county/",
        "https://myrgv.com/featured/2021/01/12/trumps-trips-to-valley-now-part-of-long-history-of-presidential-visits/",
    ]  # the third URL's date (0200/12/15) is not a date, so it is dropped
    assert listings[0].published == "2021-01-12"
    assert listings[0].title is None  # the sitemap has none; the slug stands in for it


def test_myrgv_parse_reads_headline_description_and_exact_time():
    listing = Listing("https://myrgv.com/uncategorized/2019/02/18/flood-plan-ibwc-study-recommends-dredging/", "2019-02-18", None)

    page = MyrgvSource().parse(listing.url, fixture("myrgv-article.html").decode(), listing)

    assert page.headline == "Flood plan: IBWC study recommends dredging"
    assert page.description.startswith("MERCEDES — A new hydraulic model for flood mitigation")
    assert "[" not in page.description and page.description.endswith("…")
    assert page.published_at == "2019-02-19T03:46:44Z"  # the page's own time, not the URL's day


def test_myrgv_parse_falls_back_to_the_listing_date():
    listing = Listing("https://myrgv.com/x/2019/02/18/y/", "2019-02-18", None)
    html = '<html><head><meta property="og:title" content="A flood story"></head></html>'

    assert MyrgvSource().parse(listing.url, html, listing).published_at == "2019-02-18"


def test_myrgv_parse_skips_page_without_headline():
    listing = Listing("https://myrgv.com/x/2019/02/18/y/", "2019-02-18", None)

    assert MyrgvSource().parse(listing.url, "<html><head></head></html>", listing) is None
