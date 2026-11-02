"""Authorized, reproducible inputs for historic-news evidence.

This module deliberately has no general-purpose news scraper.  A publisher is
eligible only after its authorization is recorded in ``SOURCES``; an enabled
source is rebuilt from an explicitly supplied authorized response, a valid
cache, or the checked-in authorized fixture.  The latter keeps local builds
and tests reproducible without silently reaching out to a publisher.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jsonio import read_ndjson


class HistoricNewsSourceError(RuntimeError):
    """An enabled source had neither an authorized response nor valid cache."""


@dataclass(frozen=True)
class HistoricNewsSource:
    id: str
    publisher: str
    enabled: bool
    authorization: str
    counties: tuple[str, ...]


SOURCES = (
    HistoricNewsSource(
        id="the-brownsville",
        publisher="The Brownsville",
        enabled=True,
        authorization="Authorized fixture or response retained by the project.",
        counties=("cameron",),
    ),
    HistoricNewsSource(
        id="myrgv-valley-morning-star",
        publisher="MyRGV / Valley Morning Star",
        enabled=False,
        authorization="Disabled pending recorded publisher authorization and retention approval.",
        counties=("cameron", "hidalgo", "starr", "willacy"),
    ),
)

_MAXIMUM_LENGTHS = {
    "record_id": 160,
    "headline": 300,
    "summary": 1_200,
    "published_at": 40,
    "canonical_url": 2_048,
    "location_text": 300,
    "retrieved_at": 40,
}

# A record cannot become published evidence without the fields required by the
# build, database, API, and rendered "Read original" link.  Keep that contract
# at this boundary so malformed source data fails before a partial row exists.
_REQUIRED_TEXT_FIELDS = {
    "record_id",
    "headline",
    "summary",
    "published_at",
    "canonical_url",
    "retrieved_at",
}


def _checked(record: dict, source: HistoricNewsSource) -> dict:
    """Keep only bounded, non-article metadata from one authorized record."""
    if record.get("source_publisher") != source.publisher:
        raise HistoricNewsSourceError(
            f"{source.id}: record publisher is not the enabled publisher {source.publisher!r}"
        )
    normalized = {}
    for key, maximum in _MAXIMUM_LENGTHS.items():
        value = record.get(key)
        if isinstance(value, str) and value.strip() and len(value) <= maximum:
            normalized[key] = value
        elif key in _REQUIRED_TEXT_FIELDS:
            raise HistoricNewsSourceError(
                f"{source.id}: {key} must be a non-empty string of at most {maximum} characters"
            )
        else:
            normalized[key] = None
    # These are the only fields the downstream map builder can retain.  In
    # particular, article text and any unrecognized response fields never leave
    # this boundary.
    return {
        **normalized,
        "county": record.get("county"),
        "source_publisher": source.publisher,
        "source_coordinates": record.get("source_coordinates"),
        "fixed_place_coordinates": record.get("fixed_place_coordinates"),
        "location_precision": record.get("location_precision"),
        "geometry_absence_reason": record.get("geometry_absence_reason"),
    }


def _cache_file(cache_dir: Path, source: HistoricNewsSource) -> Path:
    return cache_dir / f"{source.id}.ndjson"


def _records_from_fixture(counties: list[str], seed_dir: Path) -> list[dict]:
    return [
        {**record, "county": county}
        for county in counties
        for record in read_ndjson(seed_dir / county / "historic-news.ndjson")
    ]


def records(
    counties: list[str],
    seed_dir: Path,
    *,
    cache_dir: Path | None = None,
    authorized_responses: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Return deterministic, de-duplicated records from enabled sources only.

    ``authorized_responses`` is an explicit handoff from an approved retrieval
    step.  A response refreshes the on-disk cache only after every record has
    passed validation.  Without one, a valid cache is preferred; the committed
    fixture is the reproducible authorized response used by normal local builds.
    """
    collected: list[dict] = []
    for source in SOURCES:
        source_counties = set(counties).intersection(source.counties)
        if not source.enabled or not source_counties:
            continue
        supplied = (authorized_responses or {}).get(source.id)
        cached = _cache_file(cache_dir, source) if cache_dir else None
        if supplied is not None:
            raw_records = supplied
        elif cached and cached.exists():
            raw_records = read_ndjson(cached)
        else:
            raw_records = _records_from_fixture(sorted(source_counties), seed_dir)
            if not raw_records:
                raise HistoricNewsSourceError(
                    f"{source.id}: no authorized response or valid cache is available; no historic-news data was produced"
                )
        checked = [_checked(record, source) for record in raw_records]
        if any(record["county"] not in source_counties for record in checked):
            raise HistoricNewsSourceError(f"{source.id}: response contains a record outside the source's authorized counties")
        if supplied is not None and cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text("".join(_ndjson_line(record) for record in checked), encoding="utf-8")
        collected.extend(checked)

    # A publisher URL is the durable story identity when available.  If it is
    # unavailable, retain the entry under its required source record identity
    # instead of treating every URL-less item as a duplicate.
    chosen: dict[tuple[str, str, str], dict] = {}
    for record in sorted(
        collected,
        key=lambda item: (item["source_publisher"], item["canonical_url"] or "", item["record_id"]),
    ):
        if record["canonical_url"]:
            identity = (record["source_publisher"], "url", record["canonical_url"])
        else:
            identity = (record["source_publisher"], "record", record["record_id"])
        chosen.setdefault(identity, record)
    return sorted(chosen.values(), key=lambda item: (item["published_at"] or "", item["record_id"]))


def _ndjson_line(record: dict) -> str:
    # Stable cache bytes make an approved response reproducible and auditable.
    import json

    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
