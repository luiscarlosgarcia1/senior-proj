from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("msvcrt", reason="Windows-only lock; see test_live_signals_scheduler.py")

from rgv_flood.live_signals_scheduler_windows import LiveSignalScheduler


def test_refresh_runs_each_live_signal_command(tmp_path: Path):
    commands = (("run_nws.py",), ("run_hidalgo_rss.py",), ("run_drivetexas.py",))
    completed: list[tuple[str, ...]] = []
    scheduler = LiveSignalScheduler(
        commands,
        interval_seconds=900,
        lock_file=tmp_path / "scheduler.lock",
        run_command=completed.append,
    )

    scheduler.refresh()

    assert completed == list(commands)


def test_refresh_continues_after_a_failed_command(tmp_path: Path, caplog):
    commands = (("run_nws.py",), ("run_hidalgo_rss.py",), ("run_drivetexas.py",))
    completed: list[tuple[str, ...]] = []

    def run_command(command: tuple[str, ...]) -> None:
        completed.append(command)
        if command == commands[1]:
            raise OSError("source unavailable")

    scheduler = LiveSignalScheduler(
        commands,
        interval_seconds=900,
        lock_file=tmp_path / "scheduler.lock",
        run_command=run_command,
    )

    with caplog.at_level(logging.ERROR):
        scheduler.refresh()

    assert completed == list(commands)
    assert "run_hidalgo_rss.py" in caplog.text


def test_only_one_scheduler_starts_when_the_lock_is_contended(tmp_path: Path):
    started = Event()
    release = Event()

    def run_command(command: tuple[str, ...]) -> None:
        started.set()
        release.wait()

    first = LiveSignalScheduler(
        (("run_nws.py",),),
        interval_seconds=900,
        lock_file=tmp_path / "scheduler.lock",
        run_command=run_command,
    )
    second = LiveSignalScheduler(
        (("run_nws.py",),),
        interval_seconds=900,
        lock_file=tmp_path / "scheduler.lock",
        run_command=run_command,
    )

    assert first.start() is True
    assert started.wait(timeout=1)
    assert second.start() is False

    release.set()
