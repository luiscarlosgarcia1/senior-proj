"""The other Valley publishers, read through their sitemaps, and the roster of every source the build uses.

Most sites publish a sitemap: a list of every story's address. Three shapes cover nearly all of them:

  * `SitemapSource`: an index of sitemaps (WordPress core, Yoast) or one big list, followed to the stories;
  * `MonthlySitemapSource`: one file a month (Texas Public Radio);
  * `NexstarDailySource`: one sitemap a day, at an address that takes the date (ValleyCentral, Border Report).

The old Monitor, Brownsville Herald, Valley Morning Star and KRGV sites are no longer listed by any sitemap; `news_wayback.py`
reads them from the Wayback Machine's copies.

Reading a story's page needs the publisher's server to let us in. Nexstar's sites answer our identified
crawler with "403 Forbidden" on every article, so for them we keep only what the sitemap itself says
(address and day) and never pretend to be a browser to get past that.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import date, timedelta
from xml.etree import ElementTree

from news_fetch import Fetcher
from news_match import headline_from_slug
from news_sources import (
    _TRUNCATED,
    NEWS_NS,
    NOT_FREE,
    SITEMAP_MAX_AGE,
    KrgvSource,
    Listing,
    MyrgvSource,
    NewsSource,
    Page,
    _Head,
    date_in_url,
    to_utc,
)
from news_wayback import wayback_sources

_JSON_LD_DATE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_ITEMPROP_DATE = re.compile(r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
MAX_SITEMAP_DEPTH = 4
# Addresses that are a section of a site, not a story.
SECTION_SLUGS = frozenset(("news", "local-news", "weather", "sports", "top-stories", "national-news", "texas", "health", "politics",
                           "entertainment", "mexico", "world", "business", "video", "videos", "us", "money", "technology"))


def _local(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ElementTree.Element, name: str) -> str:
    for child in element.iter():
        if _local(child) == name and child.text and child.text.strip():
            return child.text.strip()
    return ""


def _read_sitemap(fetcher: Fetcher, url: str, *, use_cache: bool = True, max_age: float | None = None) -> ElementTree.Element | None:
    body = fetcher.get(url, use_cache=use_cache, max_age=max_age)
    if not body:
        return None
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return None


def _entry_listing(entry: ElementTree.Element) -> Listing | None:
    url = _text(entry, "loc")
    if not url:
        return None
    news = next((child for child in entry if child.tag == f"{NEWS_NS}news"), None)
    stamp = to_utc(news.findtext(f"{NEWS_NS}publication_date")) if news is not None else None
    title = ((news.findtext(f"{NEWS_NS}title") or "").strip() or None) if news is not None else None
    # Never the sitemap's <lastmod>: that is when the story was last edited, not when it was published.
    return Listing(url=url, published=stamp or date_in_url(url), title=title)


class _PageReader:
    """Reads a story page's head: headline, description, and the publication time.

    The time comes from the page's `article:published_time`, its structured data or an itemprop, then from the
    sitemap's publication date or the address. Never from a `<time>` tag (a page lists other, newer stories in
    widgets) and never from the sitemap's last-modified time: a story with no date of its own is skipped."""

    @staticmethod
    def parse(url: str, html: str, listing: Listing) -> Page | None:
        if NOT_FREE.search(html):
            return None
        head = _Head()
        head.feed(html)
        headline = head.meta.get("og:title") or head.title.strip()
        if not headline:
            return None
        candidates = (
            head.meta.get("article:published_time"), head.meta.get("og:article:published_time"),
            *(pattern.search(html).group(1) if pattern.search(html) else None for pattern in (_JSON_LD_DATE, _ITEMPROP_DATE)),
        )
        published = next((stamp for stamp in map(to_utc, candidates) if stamp), None) or listing.published
        if not published:
            return None
        description = _TRUNCATED.sub("…", head.meta.get("og:description") or head.meta.get("description") or "")
        return Page(url=url, headline=headline, description=description, published_at=published)


class SitemapSource(_PageReader):
    """A publisher whose stories are listed in sitemaps: an index to follow, or a list to read."""

    reads_pages = True
    local_sections: tuple[str, ...] = ()

    def __init__(
        self,
        id: str,
        publisher: str,
        home_url: str,
        roots: Sequence[str] | Callable[[], Iterable[str]],
        *,
        include: str | None = None,
        exclude: str | None = None,
        url_filter: str | None = None,
        kind: str = "news",
        needs_place_in_address: bool = False,
    ) -> None:
        self.id, self.publisher, self.home_url, self.kind = id, publisher, home_url, kind
        self.needs_place_in_address = needs_place_in_address
        self._roots = roots
        self._include = re.compile(include) if include else None
        self._exclude = re.compile(exclude) if exclude else None
        self._url_filter = re.compile(url_filter) if url_filter else None

    def _wanted_child(self, url: str) -> bool:
        return (self._include is None or bool(self._include.search(url))) and not (self._exclude and self._exclude.search(url))

    def _walk(self, fetcher: Fetcher, url: str, depth: int, visited: set[str]) -> Iterator[Listing]:
        if url in visited or depth > MAX_SITEMAP_DEPTH:
            return
        visited.add(url)
        root = _read_sitemap(fetcher, url, max_age=self._max_age(url))
        if root is None:
            return
        for entry in list(root):
            kind = _local(entry)
            if kind == "sitemap":
                child = _text(entry, "loc")
                if child and self._wanted_child(child):
                    yield from self._walk(fetcher, child, depth + 1, visited)
            elif kind == "url":
                listing = _entry_listing(entry)
                if listing and (self._url_filter is None or self._url_filter.search(listing.url)):
                    yield listing

    def _max_age(self, url: str) -> float | None:
        """How old a cached copy of this sitemap may be before it is read again."""
        return SITEMAP_MAX_AGE

    def listings(self, fetcher: Fetcher) -> Iterator[Listing]:
        roots = self._roots() if callable(self._roots) else self._roots
        visited: set[str] = set()
        seen: set[str] = set()
        for root in roots:
            for listing in self._walk(fetcher, root, 0, visited):
                if listing.url not in seen:
                    seen.add(listing.url)
                    yield listing


class MonthlySitemapSource(SitemapSource):
    """One sitemap a month, at an address that takes the year and month (`{yyyy}` and `{mm}`)."""

    def __init__(
        self, id: str, publisher: str, home_url: str, template: str, first_month: tuple[int, int], *,
        today: Callable[[], date] = date.today, **options,
    ) -> None:
        def months() -> Iterator[str]:
            year, month = first_month
            end = today()
            while (year, month) <= (end.year, end.month):
                yield template.format(yyyy=f"{year:04d}", mm=f"{month:02d}")
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)

        super().__init__(id, publisher, home_url, months, **options)
        self._template, self._today = template, today

    def _max_age(self, url: str) -> float | None:
        """Only this month's and last month's files still change; an older month is read once and kept."""
        end = self._today()
        previous = (end.year, end.month - 1) if end.month > 1 else (end.year - 1, 12)
        recent = {self._template.format(yyyy=f"{y:04d}", mm=f"{m:02d}") for y, m in ((end.year, end.month), previous)}
        return SITEMAP_MAX_AGE if url in recent else None


class NexstarDailySource:
    """Nexstar's sites (ValleyCentral, Border Report): one sitemap for each day. Their article pages refuse our
    identified crawler, so a story is its address, its day and a headline made from the address."""

    reads_pages = False
    kind = "news"

    def __init__(
        self, id: str, publisher: str, home_url: str, host: str, first_day: date, *,
        local_sections: tuple[str, ...] = (), needs_place_in_address: bool = False, today: Callable[[], date] = date.today,
    ) -> None:
        self.id, self.publisher, self.home_url, self.host = id, publisher, home_url, host
        self.first_day, self.local_sections, self.needs_place_in_address, self._today = first_day, local_sections, needs_place_in_address, today

    def listings(self, fetcher: Fetcher) -> Iterator[Listing]:
        end = self._today()
        day = self.first_day
        while day <= end:
            url = f"https://{self.host}/sitemap.xml?yyyy={day:%Y}&mm={day:%m}&dd={day:%d}"
            root = _read_fresh(fetcher, url, recent=(end - day).days <= 1)
            for entry in list(root) if root is not None else []:
                loc = _text(entry, "loc") if _local(entry) == "url" else ""
                if loc:
                    yield Listing(url=loc, published=day.isoformat(), title=None)
            day += timedelta(days=1)

    def page_from_listing(self, listing: Listing) -> Page | None:
        headline = headline_from_slug(listing.url)
        slug = [part for part in listing.url.split("?")[0].split("/") if part][-1].lower() if listing.url.strip("/") else ""
        if not headline or not listing.published or slug in SECTION_SLUGS:
            return None
        return Page(url=listing.url, headline=headline, description="", published_at=listing.published)

    def parse(self, url: str, html: str, listing: Listing) -> Page | None:  # pages are not read
        return None


def _read_fresh(fetcher: Fetcher, url: str, *, recent: bool) -> ElementTree.Element | None:
    """A sitemap; one from the last two days is asked for again rather than taken from the cache (it is still growing)."""
    return _read_sitemap(fetcher, url, use_cache=not recent)


def default_sources() -> list[NewsSource]:
    """Every source the build reads, news outlets first. Each id is also the id of its `data_sources` row."""
    wordpress_posts = r"post-sitemap\d*\.xml$|wp-sitemap-posts-post-\d+\.xml$"
    return [
        KrgvSource(),
        MyrgvSource(),
        NexstarDailySource(
            "news-valleycentral", "ValleyCentral (KVEO, KGBT)", "https://www.valleycentral.com", "www.valleycentral.com",
            date(2016, 1, 1), local_sections=("/news/local-news/", "/weather/"),
        ),
        NexstarDailySource(
            "news-borderreport", "Border Report (Nexstar)", "https://www.borderreport.com", "www.borderreport.com",
            date(2019, 9, 1), needs_place_in_address=True,
        ),
        SitemapSource("news-foxrgv", "Fox RGV (KFXV)", "https://foxrgv.tv", ["https://foxrgv.tv/wp-sitemap.xml"],
                      include=wordpress_posts, exclude=r"video|local-|page|categor|tag|author|user"),
        SitemapSource("news-riograndeguardian", "Rio Grande Guardian", "https://riograndeguardian.com",
                      ["https://riograndeguardian.com/sitemaps/sitemaps-r2-default-default-1.xml"], url_filter=r"/stories/"),
        SitemapSource("news-progresstimes", "Progress Times (Pharr, San Juan, Alamo)", "https://www.progresstimes.net",
                      ["https://www.progresstimes.net/wp-sitemap.xml"], include=r"posts-post-\d+\.xml$"),
        SitemapSource("news-pispp", "Port Isabel-South Padre Press", "https://www.portisabelsouthpadre.com",
                      ["https://www.portisabelsouthpadre.com/sitemap-index-1.xml"], include=r"/sitemap-\d+\.xml$", exclude="image"),
        SitemapSource("news-texasborderbusiness", "Texas Border Business", "https://texasborderbusiness.com",
                      ["https://texasborderbusiness.com/sitemap.xml"], include=r"post-sitemap\d*\.xml$"),
        MonthlySitemapSource("news-tpr", "Texas Public Radio", "https://www.tpr.org", "https://www.tpr.org/sitemap-{yyyy}{mm}.xml",
                             (2004, 1), needs_place_in_address=True),
        SitemapSource("news-texastribune", "The Texas Tribune", "https://www.texastribune.org", ["https://www.texastribune.org/sitemap.xml"],
                      include=r"post-sitemap\d*\.xml$", needs_place_in_address=True),
        SitemapSource("official-cameroncounty", "Cameron County", "https://www.cameroncountytx.gov",
                      ["https://www.cameroncountytx.gov/wp-sitemap.xml"], include=r"post-sitemap\d*\.xml$", kind="official"),
        SitemapSource("official-pharr", "City of Pharr", "https://www.pharr-tx.gov", ["https://www.pharr-tx.gov/wp-sitemap.xml"],
                      include=r"post-sitemap\d*\.xml$", kind="official"),
        SitemapSource("official-ibwc", "International Boundary and Water Commission, U.S. Section", "https://www.ibwc.gov",
                      ["https://www.ibwc.gov/wp-sitemap.xml"], include=r"post-sitemap\d*\.xml$", kind="official"),
        *wayback_sources(),  # the old sites, before 2016, from the Wayback Machine
    ]

