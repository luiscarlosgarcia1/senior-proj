"""The historic-news authorization boundary is deterministic and fail-closed."""

import pytest
from historic_news_sources import SOURCES, HistoricNewsSourceError, records


def _record(record_id: str, url: str) -> dict:
    return {
        "record_id": record_id,
        "county": "cameron",
        "headline": "Historic flooding report",
        "summary": "Project-written summary only.",
        "published_at": "2020-07-26",
        "source_publisher": "The Brownsville",
        "canonical_url": url,
        "retrieved_at": "2026-10-29T00:00:00Z",
        "article_text": "This must never be retained.",
    }


def test_authorized_response_refreshes_cache_and_deduplicates_deterministically(tmp_path):
    cache = tmp_path / "cache"
    response = [_record("later", "https://example.test/story"), _record("first", "https://example.test/story")]

    first = records(["cameron"], tmp_path / "empty-seed", cache_dir=cache, authorized_responses={"the-brownsville": response})
    cached = records(["cameron"], tmp_path / "empty-seed", cache_dir=cache)

    assert first == cached
    assert [row["record_id"] for row in cached] == ["first"]
    assert "article_text" not in cached[0]


def test_enabled_source_fails_clearly_without_authorized_response_cache_or_fixture(tmp_path):
    with pytest.raises(HistoricNewsSourceError, match="the-brownsville: no authorized response or valid cache"):
        records(["cameron"], tmp_path / "empty-seed", cache_dir=tmp_path / "cache")


def test_enabled_source_rejects_non_authorized_county_in_a_multi_county_build(tmp_path):
    response = [_record("cameron", "https://example.test/cameron"), _record("hidalgo", "https://example.test/hidalgo")]
    response[1]["county"] = "hidalgo"
    cache = tmp_path / "cache"

    with pytest.raises(HistoricNewsSourceError, match="the-brownsville: response contains a record outside the source's authorized counties"):
        records(
            ["cameron", "hidalgo"],
            tmp_path / "empty-seed",
            cache_dir=cache,
            authorized_responses={"the-brownsville": response},
        )

    assert not (cache / "the-brownsville.ndjson").exists()


@pytest.mark.parametrize("field, value", [
    ("headline", None),
    ("summary", ""),
    ("published_at", None),
    ("canonical_url", None),
    ("retrieved_at", "x" * 41),
])
def test_authorized_response_rejects_missing_required_published_metadata(tmp_path, field, value):
    response = _record("minimal", "https://example.test/minimal")
    response[field] = value

    with pytest.raises(HistoricNewsSourceError, match=f"{field} must be a non-empty string"):
        records(
            ["cameron"],
            tmp_path / "empty-seed",
            authorized_responses={"the-brownsville": [response]},
        )


def test_disabled_myrgv_source_is_registry_only_and_never_enabled():
    (myrgv,) = [source for source in SOURCES if source.id == "myrgv-valley-morning-star"]
    assert not myrgv.enabled
    assert "authorization" in myrgv.authorization.lower()
