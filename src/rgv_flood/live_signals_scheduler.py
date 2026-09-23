"""Periodic refreshes of the official live-signal snapshots."""

from __future__ import annotations

import fcntl
import logging
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Event, Thread

LOGGER = logging.getLogger(__name__)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
Command = tuple[str, ...]
CommandRunner = Callable[[Command], None]


class LiveSignalScheduler:
    """Run snapshot commands on one process at a fixed interval.

    The advisory lock is held for the scheduler's lifetime. This lets just one
    Flask worker own live refreshes, including when Werkzeug starts its reloader.
    """

    def __init__(
        self,
        commands: Iterable[Command],
        *,
        interval_seconds: int,
        lock_file: Path,
        run_command: CommandRunner | None = None,
    ) -> None:
        self.commands = tuple(commands)
        self.interval_seconds = interval_seconds
        self.lock_file = lock_file
        self.run_command = run_command or _run_command
        self._stop_event = Event()
        self._lock_handle = None
        self._thread: Thread | None = None

    def start(self) -> bool:
        """Start refreshing in the background if this process owns the lock."""
        if self._thread is not None:
            return True
        if not self._claim_lock():
            LOGGER.info("Live-signal scheduler is already owned by another process")
            return False
        self._thread = Thread(
            target=self._run, name="live-signal-scheduler", daemon=True
        )
        self._thread.start()
        return True

    def refresh(self) -> None:
        """Run every source independently so one outage does not block others."""
        for command in self.commands:
            try:
                self.run_command(command)
            except (OSError, subprocess.SubprocessError, TimeoutError):
                LOGGER.exception(
                    "Live-signal refresh command failed: %s", _command_name(command)
                )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.refresh()
            self._stop_event.wait(self.interval_seconds)

    def _claim_lock(self) -> bool:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = self.lock_file.open("a+")
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_handle.close()
            return False
        self._lock_handle = lock_handle
        return True


def build_refresh_commands(database: Path) -> tuple[Command, ...]:
    """Return the existing script invocations, targeting the app's database."""
    scripts = REPOSITORY_ROOT / "pipeline"
    return tuple(
        (sys.executable, str(scripts / script), "--output", str(database))
        for script in ("run_nws.py", "run_hidalgo_rss.py", "run_drivetexas.py")
    )


def _run_command(command: Command) -> None:
    subprocess.run(command, check=True, timeout=60)


def _command_name(command: Command) -> str:
    return next((part for part in command if part.endswith(".py")), command[0])
