"""Chat: the daily message counts (rgv_flood/chat/limits.py)."""

import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from rgv_flood.chat.limits import (
    ANON_DAILY,
    ANON_IP_DAILY,
    SIGNED_IN_DAILY,
    UsageStore,
    valley_day,
)

NOON = datetime(2026, 11, 9, 18, 0, tzinfo=UTC)  # noon in the Valley (CST, UTC-6)


@pytest.fixture()
def store(tmp_path):
    return UsageStore(tmp_path / "usage.sqlite3", pepper="pepper")


def test_the_limits_are_the_agreed_numbers():
    assert (ANON_DAILY, ANON_IP_DAILY, SIGNED_IN_DAILY) == (5, 25, 200)


def test_five_then_refused(store):
    limits = {"v:a": 5, "ip:1": 25}

    assert [store.try_consume(limits, now=NOON) for _ in range(6)] == [True] * 5 + [False]
    assert store.used("v:a", now=NOON) == 5


def test_one_key_over_means_nothing_is_counted(store):
    assert store.try_consume({"ip:1": 1}, now=NOON)

    assert store.try_consume({"v:a": 5, "ip:1": 1}, now=NOON) is False

    assert store.used("v:a", now=NOON) == 0 and store.used("ip:1", now=NOON) == 1


def test_valley_midnight_starts_a_new_day(store):
    late = datetime(2026, 11, 9, 5, 59, tzinfo=UTC)  # 23:59 on Nov 8 in the Valley
    early = late + timedelta(minutes=2)  # 00:01 on Nov 9

    assert (valley_day(late), valley_day(early)) == ("2026-11-08", "2026-11-09")
    assert store.try_consume({"v:a": 1}, now=late) and not store.try_consume({"v:a": 1}, now=late)
    assert store.try_consume({"v:a": 1}, now=early)


def test_refund_gives_a_message_back_and_never_goes_below_zero(store):
    store.try_consume({"v:a": 5}, now=NOON)

    store.refund(["v:a"], now=NOON)
    store.refund(["v:a"], now=NOON)

    assert store.used("v:a", now=NOON) == 0


def test_keys_are_hashed_in_the_file(store, tmp_path):
    store.try_consume({"u:ana@utrgv.edu": 200, "ip:203.0.113.9": 25}, now=NOON)

    with closing(sqlite3.connect(tmp_path / "usage.sqlite3")) as connection:
        dump = repr(connection.execute("select * from usage").fetchall())
    assert "ana" not in dump and "utrgv" not in dump and "203.0.113.9" not in dump


def test_old_days_are_purged(store, tmp_path):
    store.try_consume({"v:a": 5}, now=NOON)

    store.try_consume({"v:a": 5}, now=NOON + timedelta(days=4))

    with closing(sqlite3.connect(tmp_path / "usage.sqlite3")) as connection:
        assert [row[0] for row in connection.execute("select day from usage")] == ["2026-11-13"]


def test_two_threads_cannot_both_take_the_last_message(store):
    for round_number in range(50):
        barrier = threading.Barrier(2)
        results = []

        def take(key=f"v:{round_number}", barrier=barrier, results=results):
            barrier.wait()
            results.append(store.try_consume({key: 1}, now=NOON))

        threads = [threading.Thread(target=take) for _ in range(2)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]

        assert sorted(results) == [False, True]
