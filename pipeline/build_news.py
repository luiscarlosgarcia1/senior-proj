#!/usr/bin/env python3
"""Collect water-related news and official announcements from the Valley's publishers into the central database.

"Water-related" is wide: floods, rain, storms and hurricanes, drought and water supply, drainage and
water systems, anything about water (`news_match.py`). Every publisher in `news_outlets.py` (KRGV, The Monitor
and Brownsville Herald, ValleyCentral, Border Report, Fox RGV, Rio Grande Guardian, Progress Times, the
Port Isabel-South Padre Press, Texas Border Business, Texas Public Radio, the Texas Tribune, and a few county,
city and agency sites, plus the old Monitor, Herald, Morning Star and KRGV sites from the Wayback Machine, `news_wayback.py`)
is read side by side, one thread each:

  1. list its stories from its sitemaps, back to the first story the sitemaps show (no date floor);
  2. skip any whose address or title has no water word (they are never downloaded);
  3. for outlets that cover more than the Valley, also require a Valley place in the address;
  4. download the rest politely (`news_fetch.Fetcher` obeys robots.txt and crawl-delay, waits between requests to a
     host, never pretends to be a browser, leaves a host alone that keeps refusing, and caches every page in `tmp/news/`);
  5. keep a story only if it names a Valley town, county or the Valley as a whole (`news_match.py`).

One row per story goes into `news_articles` (see `database.py`): the headline, the page's own short description,
the link, where and when it was published, and its topics. Never the article text. Where a publisher's pages
refuse us (Nexstar's), the headline is made from the address and no description is stored.

Fills news_articles, and one `data_sources` row per publisher. A publisher that gave nothing this time keeps its
earlier stories, so a flaky site or a partial run never erases data.

Run:  uv run python pipeline/build_news.py [--only news-krgv,news-tpr] [--limit N] [--list]
The first run downloads tens of thousands of pages at one per second per site and takes hours; stop it any
time (Ctrl+C) and run it again: everything downloaded is kept and read from the cache. `--limit N` is a dry run:
it stops after N new downloads, prints what it found and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import threading
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from database import open_database, record_sources, replace_table
from news_fetch import NEWS_CACHE, Fetcher, normalize_url
from news_match import (
    StoryMatch,
    has_valley_place,
    headline_from_slug,
    match_story,
    mentions_flood,
    places_in,
    topics_in,
)
from news_outlets import default_sources
from news_sources import Listing, NewsSource, Page
from news_wayback import FETCH_DELAYS
from paths import DATABASE

NEWS_SINCE = "1990-01-01"  # no real floor: each publisher's sitemaps begin when its archive does
EXCERPT_LIMIT = 300
PAGE_LIMIT = 200_000  # a story's headline and description are in the first bytes of its page
HEARTBEAT_SECONDS = 60
COUNT_LABELS = (
    ("before_since", "dated before the start date"), ("slug_skipped", "with no water word in the address or title"),
    ("not_valley_address", "from outlets that cover more than the Valley, with no Valley place in the address"),
    ("unparsed", "unreadable, paywalled or undated"), ("no_match", "without a water word and a Valley place"),
    ("unfetched", "not downloadable (robots.txt, refused, or an error)"), ("error", "stopped by an error"),
)


def decode_page(body: bytes) -> str:
    """UTF-8 when the page is valid UTF-8, otherwise Windows-1252 (some KRGV pages are)."""
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def excerpt_of(description: str) -> str | None:
    """The page's description, cut at a word boundary to at most EXCERPT_LIMIT characters."""
    text = " ".join(description.split())
    if not text:
        return None
    if len(text) <= EXCERPT_LIMIT:
        return text
    return text[: EXCERPT_LIMIT - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"


def news_row(
    publisher: str, page: Page, match: StoryMatch, retrieved_at: str, *, kind: str = "news", headline_from: str = "page"
) -> dict:
    return {
        "id": hashlib.sha1(normalize_url(page.url).encode()).hexdigest()[:16],
        "publisher": publisher,
        "source_url": normalize_url(page.url),
        "headline": page.headline,
        "published_at": page.published_at,
        "excerpt": excerpt_of(page.description),
        "county": match.counties[0] if match.counties else None,
        "counties": ",".join(match.counties),
        "city": match.city,
        "places": places_in(f"{page.headline}. {page.description}"),
        "matched_terms": ",".join(match.terms),
        "topics": ",".join(match.topics),
        "kind": kind,
        "headline_from": headline_from,
        "retrieved_at": retrieved_at,
    }


def _prefilter_text(listing: Listing) -> str:
    """What to test for a water word before downloading: the sitemap's title, or the headline made from the address."""
    return listing.title or headline_from_slug(listing.url)


def _match(source: NewsSource, page: Page) -> StoryMatch | None:
    match = match_story(page.headline, page.description)
    if match is None and not getattr(source, "reads_pages", True):
        # A section of the site that is the Valley's own local news (ValleyCentral's) needs no town in the headline.
        sections = getattr(source, "local_sections", ())
        words = topics_in(page.headline)
        if words and any(section in page.url for section in sections):
            return StoryMatch(
                counties=(), city=None, terms=tuple(dict.fromkeys(w for _, w, _ in words)),
                topics=tuple(dict.fromkeys(t for _, _, t in words)), region=True,
            )
    return match


def _collect_one(
    source: NewsSource, fetcher: Fetcher, retrieved_at: str, since: str, limit: int | None,
    stop: threading.Event | None, counts: Counter, rows: dict[str, dict],
) -> None:
    reads_pages = getattr(source, "reads_pages", True)
    kind = getattr(source, "kind", "news")
    try:
        for listing in source.listings(fetcher):
            if stop is not None and stop.is_set():
                break
            if limit is not None and fetcher.stats["fetched"] >= limit:
                break
            counts["listed"] += 1
            if listing.published is not None and listing.published[:10] < since:
                counts["before_since"] += 1
                continue
            if not mentions_flood(_prefilter_text(listing)):
                counts["slug_skipped"] += 1
                continue
            if getattr(source, "needs_place_in_address", False) and not has_valley_place(headline_from_slug(listing.url), strict=True):
                counts["not_valley_address"] += 1
                continue
            if reads_pages:
                body = fetcher.get(listing.url, limit=PAGE_LIMIT)
                if body is None:
                    counts["unfetched"] += 1
                    continue
                counts["fetched"] += 1
                page = source.parse(listing.url, decode_page(body), listing)
            else:
                page = source.page_from_listing(listing)
            if page is None or page.published_at[:10] < since:
                counts["unparsed" if page is None else "before_since"] += 1
                continue
            match = _match(source, page)
            if match is None:
                counts["no_match"] += 1
                continue
            row = news_row(source.publisher, page, match, retrieved_at, kind=kind, headline_from="page" if reads_pages else "address")
            rows[row["id"]] = row
            counts["kept"] += 1
    except Exception as error:  # noqa: BLE001 - one publisher's bug must not end a crawl of nineteen
        counts["error"] += 1
        print(f"  {source.id}: stopped by {type(error).__name__}: {error}", flush=True)


def collect(
    sources: Sequence[NewsSource],
    fetcher: Fetcher,
    *,
    retrieved_at: str,
    since: str = NEWS_SINCE,
    limit: int | None = None,
    stop: threading.Event | None = None,
    heartbeat_seconds: float | None = None,
) -> tuple[list[dict], dict[str, Counter]]:
    """(rows newest first, per-source counts of what happened to each listing). Sources run side by side."""
    stats = {source.id: Counter() for source in sources}
    found: dict[str, dict[str, dict]] = {source.id: {} for source in sources}
    quiet = threading.Event()

    def heartbeat() -> None:
        while not quiet.wait(heartbeat_seconds):
            line = "  ".join(f"{sid.removeprefix('news-').removeprefix('official-')}:{c['listed']}/{c['kept']}" for sid, c in stats.items())
            print(f"[{datetime.now().astimezone():%H:%M:%S}] listed/kept  {line}  downloads {fetcher.stats['fetched']}", flush=True)

    if heartbeat_seconds:
        threading.Thread(target=heartbeat, daemon=True).start()
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
            for source in sources:
                pool.submit(_collect_one, source, fetcher, retrieved_at, since, limit, stop, stats[source.id], found[source.id])
    finally:
        quiet.set()
    rows: dict[str, dict] = {}
    for source in sources:
        rows.update(found[source.id])
    return sorted(rows.values(), key=lambda row: (row["published_at"], row["id"]), reverse=True), stats


def _source_row(source: NewsSource, count: int, counts: Counter, retrieved_at: str) -> dict:
    skipped = ", ".join(f"{counts[key]:,} {label}" for key, label in COUNT_LABELS if counts[key])
    closed = not getattr(source, "reads_pages", True)
    official = getattr(source, "kind", "news") == "official"
    return {
        "id": source.id,
        "publisher": source.publisher,
        "dataset": "Water-related announcements (headline, excerpt, link)" if official else "Water-related news stories (headline, excerpt, link)",
        "url": source.home_url,
        "retrieved_at": retrieved_at,
        "record_count": count,
        "notes": (
            f"{counts['listed']:,} stories listed in the publisher's sitemaps, {count:,} kept. Skipped: {skipped or 'none'}. "
            + (
                getattr(source, "about", None)
                or (
                    "The publisher's pages refuse our crawler, so the headline is made from the story's address and no description is stored. "
                    if closed else "Only the headline, the page's own short description and the link are stored; article text is not stored. "
                )
            )
            + "robots.txt obeyed; at most one request a second to each site."
        ),
    }


def _old_rows(database: Path) -> list[dict]:
    """Rows already in the table, whatever version of it (earlier builds had fewer columns)."""
    if not database.exists():
        return []
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            old = [dict(row) for row in connection.execute("select * from news_articles")]
        except sqlite3.OperationalError:
            return []
    for row in old:
        terms = (row.get("matched_terms") or "").replace(",", " ")
        row.setdefault("topics", ",".join(dict.fromkeys(topic for _, _, topic in topics_in(terms))) or "flood")
        row.setdefault("kind", "news")
        row.setdefault("headline_from", "page")
    return old


def main(
    database: Path = DATABASE,
    cache_dir: Path = NEWS_CACHE,
    sources: Sequence[NewsSource] | None = None,
    fetcher: Fetcher | None = None,
    limit: int | None = None,
    only: Sequence[str] | None = None,
    stop: threading.Event | None = None,
    heartbeat_seconds: float | None = None,
) -> None:
    sources = list(sources if sources is not None else default_sources())
    if only:
        unknown = sorted(set(only) - {source.id for source in sources})
        if unknown:
            raise SystemExit(f"Unknown source(s): {', '.join(unknown)}. Known: {', '.join(source.id for source in sources)}")
        sources = [source for source in sources if source.id in only]
    fetcher = fetcher or Fetcher(cache_dir, delays=FETCH_DELAYS)
    retrieved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_rows, stats = collect(sources, fetcher, retrieved_at=retrieved_at, limit=limit, stop=stop, heartbeat_seconds=heartbeat_seconds)
    for source in sources:
        print(f"{source.id}: {dict(stats[source.id])}")
    if limit is not None:  # a look at what a run does: never replaces the table with a partial set
        print(f"dry run: {len(new_rows)} stories would be kept so far; nothing was written")
        return
    if stop is not None and stop.is_set():
        print("Stopped before the end: nothing was written. Run it again to carry on; every download so far is kept.")
        return
    if not new_rows:
        raise SystemExit("No news stories were collected; news_articles was left as it was.")

    # A publisher that listed nothing, or hit an error, keeps what it had; so does one that was not part of this run.
    refreshed = {source.publisher for source in sources if stats[source.id]["listed"] and not stats[source.id]["error"]}
    kept = {row["id"]: row for row in _old_rows(database) if row["publisher"] not in refreshed}
    kept.update({row["id"]: row for row in new_rows})
    rows = sorted(kept.values(), key=lambda row: (row["published_at"], row["id"]), reverse=True)

    with open_database(database) as connection:
        replace_table(connection, "news_articles", rows)
        record_sources(connection, [
            _source_row(source, sum(1 for r in rows if r["publisher"] == source.publisher), stats[source.id], retrieved_at)
            for source in sources
        ])
    print(f"news_articles: {len(rows):,} stories ({len(new_rows):,} from this run); fetcher {dict(fetcher.stats)}")
    print("written to", database)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, help="dry run: stop after this many new downloads and write nothing")
    parser.add_argument("--only", help="comma-separated source ids to run (see --list); the others keep their rows")
    parser.add_argument("--list", action="store_true", help="show the source ids and exit")
    arguments = parser.parse_args()
    if arguments.list:
        for source in default_sources():
            print(f"{source.id:28} {source.publisher}")
        sys.exit(0)
    stopper = threading.Event()
    try:
        main(limit=arguments.limit, only=arguments.only.split(",") if arguments.only else None, stop=stopper, heartbeat_seconds=HEARTBEAT_SECONDS)
    except KeyboardInterrupt:
        stopper.set()
        print("\nInterrupted: nothing was written. Run it again to carry on; every download so far is kept.")
        sys.exit(130)
