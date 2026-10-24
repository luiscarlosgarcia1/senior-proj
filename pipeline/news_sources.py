"""What each news publisher gives us: a list of its stories with dates, and the
headline and description of one story's page.

Parsing only; downloading goes through `news_fetch.Fetcher` and storage is
`build_news.py`'s job. A new publisher is a new class with the same three
members as `NewsSource`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol
from xml.etree import ElementTree

from news_fetch import Fetcher, normalize_url

SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
NEWS_NS = "{http://www.google.com/schemas/sitemap-news/0.9}"


@dataclass(frozen=True)
class Listing:
    """One story as its publisher's sitemap lists it."""

    url: str
    published: str | None  # UTC ISO 8601 ("2018-11-03T23:15:07Z")
    title: str | None


@dataclass(frozen=True)
class Page:
    url: str
    headline: str
    description: str
    published_at: str


class NewsSource(Protocol):
    id: str
    publisher: str
    home_url: str

    def listings(self, fetcher: Fetcher) -> Iterator[Listing]: ...

    def parse(self, url: str, html: str, listing: Listing) -> Page | None: ...


def to_utc(stamp: str | None) -> str | None:
    """'2018-11-03T17:15:07-06:00' -> '2018-11-03T23:15:07Z'; None if unreadable."""
    try:
        moment = datetime.fromisoformat((stamp or "").strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Head(HTMLParser):
    """Collects the <meta> tags and <title> of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content") is not None:
                self.meta.setdefault(key.lower(), values["content"].strip())
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


NOT_FREE = re.compile(r'"isAccessibleForFree"\s*:\s*(?:false|"false")', re.IGNORECASE)


def _sitemap_entries(xml: bytes, tag: str) -> list[ElementTree.Element]:
    return ElementTree.fromstring(xml).findall(f"{SITEMAP}{tag}")


class KrgvSource:
    """KRGV Channel 5 News (krgv.com).

    Its sitemap index lists paginated news sitemaps (`sitemap-news-N.xml`, 5,000
    stories each, not in date order, so every page is read and each story is
    judged by its own `news:publication_date`) plus video and category sitemaps,
    which are skipped. Story pages carry no publication date of their own (their
    `<meta name="Date">` is the day the page was served), so the date comes from
    the sitemap entry.
    """

    id = "news-krgv"
    publisher = "KRGV Channel 5 News"
    home_url = "https://www.krgv.com"
    index_url = "https://www.krgv.com/sitemap.xml"

    def listings(self, fetcher: Fetcher) -> Iterator[Listing]:
        index = fetcher.get(self.index_url)
        if index is None:
            return
        seen: set[str] = set()
        for entry in _sitemap_entries(index, "sitemap"):
            location = (entry.findtext(f"{SITEMAP}loc") or "").strip()
            if "/sitemap-news-" not in location:
                continue
            page = fetcher.get(location)
            if page is None:
                continue
            for url in _sitemap_entries(page, "url"):
                address = normalize_url((url.findtext(f"{SITEMAP}loc") or "").strip())
                if not address or address in seen:
                    continue
                seen.add(address)
                news = url.find(f"{NEWS_NS}news")
                yield Listing(
                    url=address,
                    published=to_utc(news.findtext(f"{NEWS_NS}publication_date")) if news is not None else None,
                    title=((news.findtext(f"{NEWS_NS}title") or "").strip() or None) if news is not None else None,
                )

    def parse(self, url: str, html: str, listing: Listing) -> Page | None:
        if listing.published is None or NOT_FREE.search(html):
            return None
        head = _Head()
        head.feed(html)
        headline = head.meta.get("og:title") or head.title.strip()
        if not headline:
            return None
        description = head.meta.get("og:description") or head.meta.get("description") or ""
        return Page(url=url, headline=headline, description=description, published_at=listing.published)
