"""Historic-news evidence remains deliberately narrow and non-fabricated."""

import build_events
import pytest
from historic_news_sources import HistoricNewsSourceError


def test_authorized_historic_news_fixture_flows_to_map_rows(tmp_path):
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    response = [{
        "record_id": "one", "county": "cameron", "headline": "A", "summary": "Project summary",
        "published_at": "2020-07-26", "source_publisher": "The Brownsville",
        "canonical_url": "https://example.test/original", "source_coordinates": [-97.5, 25.9],
        "retrieved_at": "2026-10-29T00:00:00Z",
    }]

    boundary = {"type": "Polygon", "coordinates": [[[-97.9, 25.8], [-97.1, 25.8], [-97.1, 26.4], [-97.9, 26.4], [-97.9, 25.8]]]}
    (seed / "cameron" / "boundary.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":' + str(boundary).replace("'", '"') + "}]}",
        encoding="utf-8",
    )

    assert build_events.historic_news(
        ["cameron"], seed, cache_dir=tmp_path / "cache",
        authorized_responses={"the-brownsville": response},
    ) == [{
        "id": "one", "county": "cameron", "headline": "A", "summary": "Project summary", "incident_start": None, "incident_end": None,
        "published_at": "2020-07-26", "publisher": "The Brownsville", "source_url": "https://example.test/original",
        "location_text": None, "location_precision": "source_coordinate", "geometry_reason": None,
        "source_lon": -97.5, "source_lat": 25.9, "lon": -97.5, "lat": 25.9,
        "retrieved_at": "2026-10-29T00:00:00Z",
    }]


@pytest.mark.parametrize("field, value", [
    ("headline", None),
    ("summary", ""),
    ("published_at", None),
    ("canonical_url", None),
    ("retrieved_at", None),
])
def test_historic_news_build_rejects_records_missing_required_published_metadata(tmp_path, field, value):
    """A record must be publishable before the build can retain it as evidence."""
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    record = {
        "record_id": "incomplete", "headline": "A", "summary": "Project summary",
        "published_at": "2020-07-26", "source_publisher": "The Brownsville",
        "canonical_url": "https://example.test/original", "retrieved_at": "2026-10-29T00:00:00Z",
    }
    record[field] = value
    with pytest.raises(HistoricNewsSourceError, match=f"{field} must be a non-empty string"):
        build_events.historic_news(
            ["cameron"], seed, cache_dir=tmp_path / "cache",
            authorized_responses={"the-brownsville": [{**record, "county": "cameron"}]},
        )


def test_historic_news_retains_uncertain_locations_without_centroid(tmp_path):
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    (seed / "cameron" / "boundary.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-97.9,25.8],[-97.1,25.8],[-97.1,26.4],[-97.9,26.4],[-97.9,25.8]]]}}]}',
        encoding="utf-8",
    )
    response = [{
        "record_id": "countywide", "county": "cameron", "headline": "A", "summary": "Project summary",
        "published_at": "2020-07-26", "source_publisher": "The Brownsville",
        "canonical_url": "https://example.test/original", "location_text": "Cameron County, Texas",
        "location_precision": "county", "geometry_absence_reason": "The report is countywide, not a point.",
        "retrieved_at": "2026-10-29T00:00:00Z",
    }]

    (row,) = build_events.historic_news(
        ["cameron"], seed, cache_dir=tmp_path / "cache",
        authorized_responses={"the-brownsville": response},
    )

    assert (row["lon"], row["lat"], row["location_precision"]) == (None, None, "county")
    assert row["geometry_reason"] == "The report is countywide, not a point."


def test_historic_news_drops_a_coordinate_just_outside_the_county(tmp_path):
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    (seed / "cameron" / "boundary.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-97.9,25.8],[-97.1,25.8],[-97.1,26.4],[-97.9,26.4],[-97.9,25.8]]]}}]}',
        encoding="utf-8",
    )
    response = [{
        "record_id": "outside", "county": "cameron", "headline": "A", "summary": "Project summary",
        "published_at": "2020-07-26", "source_publisher": "The Brownsville",
        "canonical_url": "https://example.test/original", "source_coordinates": [-97.099, 25.9],
        "retrieved_at": "2026-10-29T00:00:00Z",
    }]

    (row,) = build_events.historic_news(
        ["cameron"], seed, cache_dir=tmp_path / "cache",
        authorized_responses={"the-brownsville": response},
    )

    assert (row["lon"], row["lat"]) == (None, None)
    assert "outside Cameron County" in row["geometry_reason"]
