"""Cleaning for water-related news stories: tidy the text, check the story, merge the same story told twice.

`clean` takes the stories that matched (rows shaped like `news_articles`) and splits them three ways:

  * `kept`      the stories the app shows, with tidied headline and excerpt;
  * `copies`    the same story from another outlet (or a re-post) within three days, kept for citation but not counted twice;
  * `rejected`  stories that fail a check, with the reason.

Copies and rejects carry their whole row, so nothing is lost and the rules can change without a new crawl: feed
everything back through `clean` (use `as_row` to drop the extra columns) and the result follows the new rules.
`clean` is a pure function of its input, so it is safe to run again on its own output.

Nothing here rewrites a headline or an excerpt: text is only decoded (HTML codes), spaced evenly, or cut at the end
where it is the outlet's own name. An excerpt a site repeats on many stories is dropped, never replaced.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import NamedTuple

from news_match import PLACE_NAME_TERMS, topics_in

EARLIEST = date(1990, 1, 1)
MERGE_WITHIN_DAYS = 3
MIN_HEADLINE = 12
REPEATED_EXCERPT = 3  # the same description on this many stories of one outlet is the site's, not the story's

# An outlet's own name at the end of its headlines ("... | FOX RGV"). Only these exact outlets, only their own names.
OWN_NAME_TAILS: dict[str, tuple[str, ...]] = {
    "Fox RGV (KFXV)": ("FOX RGV",),
    "Rio Grande Guardian": ("Rio Grande Guardian",),
    "Cameron County": ("Cameron County",),
    "City of Pharr": ("City of Pharr",),
    "The Texas Tribune": ("The Texas Tribune",),
    "International Boundary and Water Commission, U.S. Section": ("IBWC",),
}
_TAILS = {
    publisher: re.compile(r"\s+[|–—-]\s+(?:" + "|".join(map(re.escape, names)) + r")\s*$", re.IGNORECASE)
    for publisher, names in OWN_NAME_TAILS.items()
}
# What `clean` adds to the rows it sets aside.
EXTRA_COLUMNS = ("article_id", "reason")


class CleanResult(NamedTuple):
    kept: list[dict]
    copies: list[dict]
    rejected: list[dict]


def as_row(stored: dict) -> dict:
    """A copy or rejected row as the story it was: without the columns `clean` added."""
    return {key: value for key, value in stored.items() if key not in EXTRA_COLUMNS}


def _tidy(text: str) -> str:
    return " ".join(html.unescape(text).split())


def _tidy_row(story: dict) -> dict:
    tidied = dict(story)
    headline = _tidy(story["headline"])
    tail = _TAILS.get(story["publisher"])
    tidied["headline"] = tail.sub("", headline).strip() if tail else headline
    tidied["excerpt"] = (_tidy(story["excerpt"]) or None) if story["excerpt"] else story["excerpt"]
    return tidied


def _day(stamp: str) -> date | None:
    try:
        return date.fromisoformat((stamp or "")[:10])
    except ValueError:
        return None


def _problem(story: dict, today: date) -> str | None:
    day = _day(story["published_at"])
    if day is None or day < EARLIEST or day > today + timedelta(days=1):
        return "bad_date"
    if len(story["headline"]) < MIN_HEADLINE:
        return "short_headline"
    terms = [term for term in story["matched_terms"].split(",") if term]
    if terms and set(terms) <= PLACE_NAME_TERMS:
        return "place_name_only"
    return None


def _without_place_names(story: dict) -> dict:
    """Drop a place name ("rio grande") from the water words, and the topic only it gave."""
    terms = [term for term in story["matched_terms"].split(",") if term]
    real = [term for term in terms if term not in PLACE_NAME_TERMS]
    if len(real) == len(terms):
        return story
    topics = dict.fromkeys(topic for _, _, topic in topics_in(" ".join(real)))
    return story | {"matched_terms": ",".join(real), "topics": ",".join(topics)}


def _headline_key(headline: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()


def _best_first(story: dict) -> tuple:
    """Which of two copies to keep: the publisher's own headline, then one with an excerpt, then the earlier."""
    return (story["headline_from"] != "page", not story["excerpt"], story["published_at"], story["id"])


def _merge(stories: list[dict]) -> tuple[list[dict], list[dict]]:
    groups: dict[str, list[dict]] = {}
    for story in stories:
        groups.setdefault(_headline_key(story["headline"]), []).append(story)
    kept: list[dict] = []
    copies: list[dict] = []
    for group in groups.values():
        group.sort(key=lambda story: (story["published_at"], story["id"]))
        clusters: list[list[dict]] = []
        for story in group:
            last = clusters[-1][-1] if clusters else None
            if last is not None and (_day(story["published_at"]) - _day(last["published_at"])).days <= MERGE_WITHIN_DAYS:
                clusters[-1].append(story)
            else:
                clusters.append([story])
        for cluster in clusters:
            best = min(cluster, key=_best_first)
            kept.append(best)
            copies.extend(story | {"article_id": best["id"], "reason": "same_story"} for story in cluster if story is not best)
    return kept, copies


def _newest_first(stories: list[dict]) -> list[dict]:
    return sorted(stories, key=lambda story: (story["published_at"], story["id"]), reverse=True)


def clean(stories: list[dict], *, today: date | None = None) -> CleanResult:
    today = today or datetime.now().astimezone().date()
    rejected: list[dict] = []
    passed: list[dict] = []
    for story in map(_tidy_row, stories):
        problem = _problem(story, today)
        if problem:
            rejected.append(story | {"reason": problem})
        else:
            passed.append(_without_place_names(story))

    repeated = Counter((story["publisher"], story["excerpt"]) for story in passed if story["excerpt"])
    passed = [
        story | {"excerpt": None} if story["excerpt"] and repeated[(story["publisher"], story["excerpt"])] >= REPEATED_EXCERPT else story
        for story in passed
    ]

    kept, copies = _merge(passed)
    return CleanResult(_newest_first(kept), _newest_first(copies), _newest_first(rejected))
