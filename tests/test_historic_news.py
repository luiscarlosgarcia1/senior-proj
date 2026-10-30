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

    assert build_events.historic_news(["cameron"], Path(seed)) == [{
        "id": "one", "county": "cameron", "headline": "A", "summary": "Project summary",
        "published_at": "2020-07-26", "publisher": "The Brownsville", "source_url": "https://example.test/original",
        "source_lon": -97.5, "source_lat": 25.9, "lon": -97.5, "lat": 25.9,
        "retrieved_at": "2026-10-29T00:00:00Z",
    }]
