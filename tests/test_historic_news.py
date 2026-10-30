"""Historic-news seed ingestion stays deterministic and deliberately narrow."""

from pathlib import Path

import build_events


def test_authorized_historic_news_fixture_flows_to_map_rows(tmp_path):
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    (seed / "cameron" / "historic-news.ndjson").write_text(
        '{"record_id":"one","headline":"A","summary":"Project summary","published_at":"2020-07-26",'
        '"source_publisher":"The Brownsville","canonical_url":"https://example.test/original",'
        '"source_coordinates":[-97.5,25.9],"retrieved_at":"2026-10-29T00:00:00Z"}\n',
        encoding="utf-8",
    )

    boundary = {"type": "Polygon", "coordinates": [[[-97.9, 25.8], [-97.1, 25.8], [-97.1, 26.4], [-97.9, 26.4], [-97.9, 25.8]]]}
    (seed / "cameron" / "boundary.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":' + str(boundary).replace("'", '"') + "}]}",
        encoding="utf-8",
    )

    assert build_events.historic_news(["cameron"], Path(seed)) == [{
        "id": "one", "county": "cameron", "headline": "A", "summary": "Project summary",
        "published_at": "2020-07-26", "publisher": "The Brownsville", "source_url": "https://example.test/original",
        "location_text": None, "location_precision": "source_coordinate", "geometry_reason": None,
        "source_lon": -97.5, "source_lat": 25.9, "lon": -97.5, "lat": 25.9,
        "retrieved_at": "2026-10-29T00:00:00Z",
    }]


def test_historic_news_retains_uncertain_locations_without_centroid(tmp_path):
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    (seed / "cameron" / "boundary.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-97.9,25.8],[-97.1,25.8],[-97.1,26.4],[-97.9,26.4],[-97.9,25.8]]]}}]}',
        encoding="utf-8",
    )
    (seed / "cameron" / "historic-news.ndjson").write_text(
        '{"record_id":"countywide","headline":"A","summary":"Project summary","published_at":"2020-07-26",'
        '"source_publisher":"The Brownsville","canonical_url":"https://example.test/original",'
        '"location_text":"Cameron County, Texas","location_precision":"county",'
        '"geometry_absence_reason":"The report is countywide, not a point.","retrieved_at":"2026-10-29T00:00:00Z"}\n',
        encoding="utf-8",
    )

    (row,) = build_events.historic_news(["cameron"], seed)

    assert (row["lon"], row["lat"], row["location_precision"]) == (None, None, "county")
    assert row["geometry_reason"] == "The report is countywide, not a point."


def test_historic_news_drops_a_coordinate_just_outside_the_county(tmp_path):
    seed = tmp_path / "seed"
    (seed / "cameron").mkdir(parents=True)
    (seed / "cameron" / "boundary.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-97.9,25.8],[-97.1,25.8],[-97.1,26.4],[-97.9,26.4],[-97.9,25.8]]]}}]}',
        encoding="utf-8",
    )
    (seed / "cameron" / "historic-news.ndjson").write_text(
        '{"record_id":"outside","headline":"A","summary":"Project summary","published_at":"2020-07-26",'
        '"source_publisher":"The Brownsville","canonical_url":"https://example.test/original",'
        '"source_coordinates":[-97.099,25.9],"retrieved_at":"2026-10-29T00:00:00Z"}\n',
        encoding="utf-8",
    )

    (row,) = build_events.historic_news(["cameron"], seed)

    assert (row["lon"], row["lat"]) == (None, None)
    assert "outside Cameron County" in row["geometry_reason"]
