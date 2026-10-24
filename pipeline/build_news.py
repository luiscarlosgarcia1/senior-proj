#!/usr/bin/env python3
"""Collect flood-related news stories, 2018 on, into the central database.

For each publisher in `news_sources.py` this lists its stories (from its
sitemaps), skips those dated before 2018 or whose headline has no flood term,
downloads the rest politely (`news_fetch.Fetcher` obeys robots.txt, waits
between requests and caches every page in `tmp/news/`), and keeps a story only
if it names a flood term and a place in one of the four counties
(`news_match.py`). One row per story goes into `news_articles` (see
`database.py`): the headline, the page's own short description, the link and
where it was published. Never the article text.

Fills news_articles, and one `data_sources` row per publisher.

Run:  uv run python pipeline/build_news.py [--limit N]
Safe to re-run (replaces only its own table). The first run downloads many
pages at one per second; later runs read the cache. `--limit N` is a dry run: it
stops after N new downloads, prints what it found and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from database import open_database, record_sources, replace_table
from news_fetch import NEWS_CACHE, Fetcher, normalize_url
from news_match import StoryMatch, match_story, mentions_flood, places_in
from news_sources import KrgvSource, Listing, MyrgvSource, NewsSource, Page
from paths import DATABASE

NEWS_SINCE = "2018-01-01"
EXCERPT_LIMIT = 300


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


def news_row(publisher: str, page: Page, match: StoryMatch, retrieved_at: str) -> dict:
    return {
        "id": hashlib.sha1(normalize_url(page.url).encode()).hexdigest()[:16],
        "publisher": publisher,
        "source_url": normalize_url(page.url),
        "headline": page.headline,
        "published_at": page.published_at,
        "excerpt": excerpt_of(page.description),
        "county": match.counties[0],
        "counties": ",".join(match.counties),
        "city": match.city,
        "places": places_in(f"{page.headline}. {page.description}"),
        "matched_terms": ",".join(match.terms),
        "retrieved_at": retrieved_at,
    }


def _may_be_flood(listing: Listing) -> bool:
    """Cheap test on the sitemap's title, or the address's headline words when it has no title."""
    return mentions_flood(listing.title or listing.url.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))


def collect(
    sources: Sequence[NewsSource],
    fetcher: Fetcher,
    *,
    retrieved_at: str,
    since: str = NEWS_SINCE,
    limit: int | None = None,
) -> tuple[list[dict], dict[str, Counter]]:
    """(rows newest first, per-source counts of what happened to each listing)."""
    rows: dict[str, dict] = {}
    stats: dict[str, Counter] = {}
    for source in sources:
        counts = stats[source.id] = Counter()
        try:
            for listing in source.listings(fetcher):
                if limit is not None and fetcher.stats["fetched"] >= limit:
                    break
                counts["listed"] += 1
                if listing.published is not None and listing.published[:10] < since:
                    counts["before_since"] += 1
                    continue
                if not _may_be_flood(listing):
                    counts["slug_skipped"] += 1
                    continue
                body = fetcher.get(listing.url)
                if body is None:
                    counts["unfetched"] += 1
                    continue
                counts["fetched"] += 1
                page = source.parse(listing.url, decode_page(body), listing)
                if page is None or page.published_at[:10] < since:
                    counts["unparsed" if page is None else "before_since"] += 1
                    continue
                match = match_story(page.headline, page.description)
                if match is None:
                    counts["no_match"] += 1
                    continue
                row = news_row(source.publisher, page, match, retrieved_at)
                rows[row["id"]] = row
                counts["kept"] += 1
        except (OSError, ValueError) as error:  # a publisher that is down or serves a broken sitemap
            counts["error"] += 1
            print(f"  {source.id}: skipped the rest ({error!r})", flush=True)
    return sorted(rows.values(), key=lambda row: (row["published_at"], row["id"]), reverse=True), stats


def _source_row(source: NewsSource, count: int, counts: Counter, retrieved_at: str) -> dict:
    skipped = ", ".join(f"{counts[key]} {label}" for key, label in (
        ("before_since", "dated before 2018"), ("slug_skipped", "with no flood term in the headline"),
        ("unparsed", "unreadable or paywalled"), ("no_match", "without a flood term and a county place"),
        ("unfetched", "not downloadable (robots.txt or an error)"),
    ) if counts[key])
    return {
        "id": source.id,
        "publisher": source.publisher,
        "dataset": "Flood-related news stories (headline, excerpt, link)",
        "url": source.home_url,
        "retrieved_at": retrieved_at,
        "record_count": count,
        "notes": (
            f"{counts['listed']} stories listed in the publisher's sitemaps, {count} kept. Skipped: {skipped or 'none'}. "
            "Only headlines, the page's own description and links are stored. robots.txt obeyed, one request per second."
        ),
    }


def main(
    database: Path = DATABASE,
    cache_dir: Path = NEWS_CACHE,
    sources: Sequence[NewsSource] | None = None,
    fetcher: Fetcher | None = None,
    limit: int | None = None,
) -> None:
    sources = sources if sources is not None else [KrgvSource(), MyrgvSource()]
    fetcher = fetcher or Fetcher(cache_dir)
    retrieved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows, stats = collect(sources, fetcher, retrieved_at=retrieved_at, limit=limit)
    if limit is not None:  # a look at what a run does: never replaces the table with a partial set
        for source in sources:
            print(f"{source.id}: {dict(stats[source.id])}")
        print(f"dry run: {len(rows)} stories would be kept so far; nothing was written")
        return
    if not rows:
        raise SystemExit("No news stories were collected; news_articles was left as it was.")

    with open_database(database) as connection:
        replace_table(connection, "news_articles", rows)
        record_sources(connection, [
            _source_row(source, sum(1 for r in rows if r["publisher"] == source.publisher), stats[source.id], retrieved_at)
            for source in sources
        ])

    for source in sources:
        print(f"{source.id}: {dict(stats[source.id])}")
    print(f"news_articles: {len(rows)} stories from {len(sources)} publishers; fetcher {dict(fetcher.stats)}")
    print("written to", database)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, help="dry run: stop after this many new downloads and write nothing")
    main(limit=parser.parse_args().limit)
