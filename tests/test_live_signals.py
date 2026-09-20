import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hidalgo_rss import HIDALGO_PUBLIC_NOTICE_FEED, ingest_hidalgo_public_notices
from live_signals import LiveSignal, LiveSignalStore, SignalValidationError

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


def _signal(**changes: object) -> LiveSignal:
    values = {
        "source": "fixture-nws",
        "native_id": "alert-123",
        "provenance": "official",
        "source_url": "https://example.test/alerts/123",
        "source_publisher": "National Weather Service",
        "source_channel": "api",
        "summary": "Flood warning for Hidalgo County.",
        "source_attributes": {"event": "Flood Warning"},
        "county_slugs": ("hidalgo",),
        "inclusion_basis": "source_geometry_intersection",
        "source_geometry": {"type": "Polygon", "coordinates": []},
        "published_at": "2026-09-20T11:00:00Z",
        "expires_at": "2026-09-20T18:00:00Z",
    }
    values.update(changes)
    return LiveSignal(**values)


def test_fixture_run_keeps_live_signals_separate_and_source_faithful(
    tmp_path: Path,
) -> None:
    database = tmp_path / "live-signals.sqlite3"
    store = LiveSignalStore(database)

    result = store.ingest_fixture(
        Path(__file__).parent / "fixtures" / "live-signals" / "official-signals.json",
        retrieved_at=NOW,
    )

    assert result.inserted == 2
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "select source, native_id, provenance, source_geometry_json, is_mappable, "
            "county_slugs_json, source_attributes_json from live_signals order by native_id"
        ).fetchall()
        assert rows == [
            (
                "fixture-nws",
                "alert-123",
                "official",
                '{"coordinates":[],"type":"Polygon"}',
                1,
                '["hidalgo"]',
                '{"event":"Flood Warning"}',
            ),
            (
                "fixture-hidalgo-rss",
                "hidalgo-notice-1",
                "official",
                None,
                0,
                '["hidalgo"]',
                '{"guid":"hidalgo-notice-1","title":"Road advisory"}',
            ),
        ]
        assert (
            connection.execute(
                "select count(*) from sqlite_master where type='table' and name='records'"
            ).fetchone()[0]
            == 0
        )


def test_upsert_uses_source_native_identity_and_preserves_first_seen(
    tmp_path: Path,
) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")
    store.ingest("fixture-nws", [_signal()], retrieved_at=NOW, reconcile=False)

    result = store.ingest(
        "fixture-nws",
        [
            _signal(
                summary="Updated source wording.",
                source_attributes={"event": "Flash Flood Warning"},
            )
        ],
        retrieved_at=NOW + timedelta(minutes=5),
        reconcile=False,
    )

    assert result.updated == 1
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("select count(*) from live_signals").fetchone()[0] == 1
        )
        assert connection.execute(
            "select summary, first_seen_at, last_seen_at from live_signals"
        ).fetchone() == (
            "Updated source wording.",
            "2026-09-20T12:00:00Z",
            "2026-09-20T12:05:00Z",
        )


def test_only_a_successful_complete_snapshot_can_close_absent_signals(
    tmp_path: Path,
) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")
    store.ingest("fixture-txdot", [_signal(source="fixture-txdot")], retrieved_at=NOW)

    store.ingest(
        "fixture-txdot",
        [_signal(source="fixture-txdot", summary="Partial response")],
        retrieved_at=NOW + timedelta(minutes=15),
        complete=False,
    )
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("select summary from live_signals").fetchone()[0] == (
            "Flood warning for Hidalgo County."
        )
    store.ingest("fixture-txdot", [], retrieved_at=NOW + timedelta(minutes=30))
    result = store.ingest("fixture-txdot", [], retrieved_at=NOW + timedelta(minutes=45))

    assert result.terminalized == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "select lifecycle_state, terminal_reason from live_signals"
        ).fetchone() == (
            "inactive",
            "absent_from_two_successful_polls",
        )


def test_invalid_scope_and_inferred_geometry_are_rejected(tmp_path: Path) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")

    with pytest.raises(SignalValidationError, match="source geometry"):
        store.ingest(
            "fixture-nws",
            [_signal(source_geometry=None, geometry_absence_reason=None)],
            retrieved_at=NOW,
        )
    with pytest.raises(SignalValidationError, match="canonical county"):
        store.ingest(
            "fixture-nws",
            [_signal(county_slugs=("outside-rgv",))],
            retrieved_at=NOW,
        )


def test_terminal_records_are_purged_to_minimal_tombstones_after_30_days(
    tmp_path: Path,
) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")
    store.ingest("fixture-txdot", [_signal(source="fixture-txdot")], retrieved_at=NOW)
    store.ingest("fixture-txdot", [], retrieved_at=NOW + timedelta(minutes=15))
    store.ingest("fixture-txdot", [], retrieved_at=NOW + timedelta(minutes=30))

    purged = store.purge_terminal_records(now=NOW + timedelta(days=31))

    assert purged == 1
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("select count(*) from live_signals").fetchone()[0] == 0
        )
        assert connection.execute(
            "select source, native_id, terminal_reason from live_signal_tombstones"
        ).fetchone() == (
            "fixture-txdot",
            "alert-123",
            "absent_from_two_successful_polls",
        )


def test_hidalgo_public_notice_rss_run_persists_source_faithful_official_notices(
    tmp_path: Path,
) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Public Notice</title>
      <item>
        <guid isPermaLink="false">notice-2026-09-20</guid>
        <title>Road maintenance advisory</title>
        <link>https://www.hidalgocounty.us/AlertCenter.aspx?AID=99</link>
        <description>County crews will perform maintenance.</description>
        <pubDate>Sun, 20 Sep 2026 10:30:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    result = ingest_hidalgo_public_notices(store, feed, retrieved_at=NOW)

    assert result.inserted == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "select source, native_id, provenance, source_url, source_channel, "
            "published_at, is_mappable, geometry_absence_reason "
            "from live_signals"
        ).fetchone() == (
            HIDALGO_PUBLIC_NOTICE_FEED,
            "notice-2026-09-20",
            "official",
            "https://www.hidalgocounty.us/AlertCenter.aspx?AID=99",
            "rss",
            "2026-09-20T10:30:00Z",
            0,
            "The RSS item supplies no geometry.",
        )
        attributes = connection.execute(
            "select source_attributes_json from live_signals"
        ).fetchone()[0]
    assert json.loads(attributes) == {
        "description": "County crews will perform maintenance.",
        "feed_url": HIDALGO_PUBLIC_NOTICE_FEED,
        "guid": "notice-2026-09-20",
        "title": "Road maintenance advisory",
    }


def test_hidalgo_rss_notice_uses_source_provided_georss_geometry(tmp_path: Path) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")
    feed = """<rss xmlns:georss="http://www.georss.org/georss"><channel><item>
      <guid>notice-with-geometry</guid><title>Flood advisory</title>
      <link>https://www.hidalgocounty.us/AlertCenter.aspx?AID=100</link>
      <pubDate>Sun, 20 Sep 2026 10:30:00 GMT</pubDate>
      <georss:point>26.12 -98.24</georss:point>
    </item></channel></rss>"""

    ingest_hidalgo_public_notices(store, feed, retrieved_at=NOW)

    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "select source_geometry_json, is_mappable, geometry_absence_reason "
            "from live_signals"
        ).fetchone() == ('{"coordinates":[-98.24,26.12],"type":"Point"}', 1, None)


def test_hidalgo_rss_skips_items_without_a_source_publication_timestamp(
    tmp_path: Path,
) -> None:
    store = LiveSignalStore(tmp_path / "live-signals.sqlite3")
    feed = """<rss><channel><item><guid>undated-notice</guid>
      <title>Undated notice</title>
      <link>https://www.hidalgocounty.us/AlertCenter.aspx?AID=101</link>
    </item></channel></rss>"""

    result = ingest_hidalgo_public_notices(store, feed, retrieved_at=NOW)

    assert result.inserted == 0
