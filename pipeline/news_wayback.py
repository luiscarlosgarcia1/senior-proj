"""Old Valley news from the Internet Archive's Wayback Machine.

The Monitor, the Brownsville Herald and the Valley Morning Star moved to myrgv.com in 2016, and KRGV changed
its site around then: their sitemaps today begin where the new sites do. The Wayback Machine kept copies of
the old pages, and its index (the CDX server) lists them by address, so stories back to the mid-2000s can be
found without guessing.

For each old site we ask the index for pages that loaded (HTTP 200, HTML) whose *address* has a water word;
these papers put the headline's first words in the address (`/articles/alamo-27894-body-canal.html`). The first
capture of each address is fetched as the publisher served it (`.../web/<time>id_/<address>`), and the story's
headline and publication date are read from the page. The stored link goes to the archived copy, because the
publisher's own address no longer works.

Nothing here is dated by when the Wayback Machine happened to copy the page: a story with no date of its own
(none in the page, none in the address) is skipped. Old pages' descriptions are just the headline and its tags, so
no description is kept.

The archive is one host, so it is asked slowly (`DELAY` seconds apart; it is slowed further if it asks us to).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlencode, urlsplit

from news_fetch import Fetcher
from news_match import headline_from_slug
from news_sources import Listing, Page, _Head, date_in_url, to_utc

HOST = "web.archive.org"
DELAY = 2.5  # seconds between requests to the archive
FETCH_DELAYS = {HOST: DELAY}
INDEX = f"https://{HOST}/cdx/search/cdx"
INDEX_PAGE = 5000  # rows asked for at a time
MAX_INDEX_PAGES = 200

# A coarse water filter run by the index itself; `news_match.mentions_flood` is the exact one, run here afterwards.
WATER_ROOTS = (
    "flood", "inundaci", "rain", "storm", "hurricane", "huracan", "drought", "sequia", "drain", "ditch", "canal", "levee",
    "resaca", "water", "agua", "irrigat", "sewer", "reservoir", "lluvia", "tormenta", "cyclone", "downpour", "deluge",
    "falcon", "amistad", "tidal", "wash", "tropical",
)
WATER_ADDRESS = "original:(?i).*(" + "|".join(WATER_ROOTS) + ").*"
NOT_A_STORY = re.compile(r"\.(?:jpe?g|png|gif|pdf|css|js|ico|xml|swf|mp3|mp4|zip)$", re.IGNORECASE)
# The old papers' titles end with their tags and their name: "Man's body found | alamo, body, canal - Now - TheMonitor.com".
PAPER_TITLE_TAIL = (
    r"\s*\|.*$|\s+-\s+(?:[A-Za-z ]+\s+-\s+)?(?:TheMonitor\.com|The Monitor|Brownsville Herald|Valley Morning Star)$"
)
ARCHIVE_NOTE = (
    "These are the old site's pages as the Internet Archive's Wayback Machine copied them (the publisher's own addresses "
    "no longer work), and each link goes to the archived copy. Only the headline and the page's own publication date are "
    "stored: a story is kept only if the page or its address gives a day, never the day it was archived. "
    "No description is stored because those pages' descriptions only repeat the headline; article text is not stored. "
    "The archive is asked for one page every few seconds."
)
MYRGV_BEGINS = "2015-12-31"  # the last day before the live myrgv.com sitemaps begin (2016); these old domains were copied into 2019
_ARCHIVE_ID = re.compile(r"^(https://web\.archive\.org/web/\d+)id_/")
_DEFAULT_PORT = re.compile(r"^(https://web\.archive\.org/web/\d+/https?://[^/:]+):(?:80|443)/")


def parse_index(text: str) -> tuple[list[tuple[str, str]], str | None]:
    """((address, capture time) rows, the key to carry on from or None) from the index's text answer.
    When there is more, the rows are followed by an empty line and then that key."""
    rows: list[tuple[str, str]] = []
    lines = text.splitlines()
    for number, line in enumerate(lines):
        if not line.strip():
            rest = [later.strip() for later in lines[number + 1:] if later.strip()]
            return rows, (rest[0] if rest else None)
        original, _, stamp = line.strip().rpartition(" ")
        if original and stamp.isdigit() and len(stamp) == 14:
            rows.append((original, stamp))
    return rows, None


def _story_key(original: str) -> str:
    """The same story under one key: no www, no port, and no trailing words after '.html/' (an old duplicate form)."""
    parts = urlsplit(original)
    host = (parts.hostname or "").removeprefix("www.")
    return host + re.sub(r"(\.html?)/.*$", r"\1", parts.path)


def citation_url(fetch_url: str) -> str:
    """The archived copy with the archive's own banner (the link a reader should follow), from the raw-copy address."""
    return _DEFAULT_PORT.sub(r"\1/", _ARCHIVE_ID.sub(r"\1/", fetch_url))


class WaybackSource:
    """One old site, read from the Wayback Machine's copies of it."""

    reads_pages = True
    kind = "news"
    needs_place_in_address = False
    local_sections: tuple[str, ...] = ()
    about = ARCHIVE_NOTE

    def __init__(
        self, id: str, publisher: str, home_url: str, domain: str, *, until: str | None = None, strip_title: str | None = None
    ) -> None:
        self.id, self.publisher, self.home_url, self.domain, self.until = id, publisher, home_url, domain, until
        self._cut = re.compile(strip_title) if strip_title else None

    def _index_url(self, resume_key: str | None) -> str:
        parameters = [
            ("url", f"{self.domain}/*"), ("output", "text"), ("fl", "original,timestamp"), ("collapse", "urlkey"),
            ("filter", "statuscode:200"), ("filter", "mimetype:text/html"), ("filter", WATER_ADDRESS),
            ("limit", str(INDEX_PAGE)), ("showResumeKey", "true"),
        ]
        if self.until:
            parameters.append(("to", self.until.replace("-", "")))
        url = f"{INDEX}?{urlencode(parameters)}"
        return f"{url}&resumeKey={resume_key}" if resume_key else url

    def listings(self, fetcher: Fetcher) -> Iterator[Listing]:
        seen: set[str] = set()
        key: str | None = None
        for _ in range(MAX_INDEX_PAGES):
            body = fetcher.get(self._index_url(key))
            if not body:
                return
            rows, next_key = parse_index(body.decode("utf-8", errors="replace"))
            for original, stamp in rows:
                story = _story_key(original)
                if "?" in original or NOT_A_STORY.search(original) or story in seen:
                    continue
                seen.add(story)
                yield Listing(
                    url=f"https://{HOST}/web/{stamp}id_/{original}",
                    published=date_in_url(original),
                    title=headline_from_slug(original),
                )
            if not rows or not next_key or next_key == key:
                return
            key = next_key

    def parse(self, url: str, html: str, listing: Listing) -> Page | None:
        head = _Head()
        head.feed(html)
        meta = {name.lower(): value for name, value in head.meta.items()}
        headline = meta.get("og:title") or head.title
        headline = " ".join((self._cut.sub("", headline) if self._cut else headline).split())
        stamps = (meta.get("publication_date"), meta.get("article:published_time"), listing.published)
        published = next((stamp for stamp in map(to_utc, stamps) if stamp), None)
        if not headline or not published:
            return None
        return Page(url=citation_url(url), headline=headline, description="", published_at=published)


def wayback_sources() -> list[WaybackSource]:
    """The old sites worth asking the archive for. Each stops where its live sitemaps begin, so no story is listed twice."""
    return [
        WaybackSource("news-wayback-themonitor", "The Monitor (via Wayback Machine)", "https://www.themonitor.com",
                      "themonitor.com", until=MYRGV_BEGINS, strip_title=PAPER_TITLE_TAIL),
        WaybackSource("news-wayback-brownsvilleherald", "Brownsville Herald (via Wayback Machine)", "https://www.brownsvilleherald.com",
                      "brownsvilleherald.com", until=MYRGV_BEGINS, strip_title=PAPER_TITLE_TAIL),
        WaybackSource("news-wayback-valleymorningstar", "Valley Morning Star (via Wayback Machine)", "https://www.valleymorningstar.com",
                      "valleymorningstar.com", until=MYRGV_BEGINS, strip_title=PAPER_TITLE_TAIL),
        # Some of KRGV's old pages have only the station's name as a title; they have no headline and are skipped.
        WaybackSource("news-wayback-krgv", "KRGV Channel 5 (via Wayback Machine)", "https://www.krgv.com", "krgv.com",
                      until="2016-12-31", strip_title=r"(?:\s+-\s+)?NEWSCHANNEL 5$"),
    ]
