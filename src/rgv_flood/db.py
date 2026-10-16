"""Read-only access to the central database.

The app never writes: connections open the file read-only and refuse writes
even through a pragma. The live-alert refresher is the only writer, and the
database runs in WAL mode, so reads never wait on it. Before the pipeline has
built the database, queries return None (`rows`) or nothing (`app_rows`) and
the file is not created.

Each worker thread keeps one connection open rather than opening the file for
every query; it is reopened if the file is replaced (a fresh build).
"""

from __future__ import annotations

import sqlite3
import stat
import threading
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._local = threading.local()

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _connection(self) -> sqlite3.Connection | None:
        """This thread's connection, or None while the database hasn't been built."""
        try:
            info = self.path.stat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode):
            return None
        file = (info.st_dev, info.st_ino)
        held = getattr(self._local, "held", None)
        if held and held[0] == file:
            return held[1]
        if held:
            held[1].close()
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = 1")
        self._local.held = (file, connection)
        return connection

    def rows(self, query: str, parameters: tuple | dict = ()) -> list[dict] | None:
        """Rows of a query as dicts, or None when the database hasn't been built yet."""
        connection = self._connection()
        if connection is None:
            return None
        return [dict(row) for row in connection.execute(query, parameters)]

    def app_rows(self, query: str, parameters: tuple | dict = ()) -> list[dict]:
        return self.rows(query, parameters) or []

    def scalar(self, query: str, parameters: tuple | dict = ()):
        """The first column of the first row, or None."""
        rows = self.rows(query, parameters)
        return next(iter(rows[0].values())) if rows else None


def get_db(request: Request) -> Database:
    """FastAPI dependency: the app's database."""
    return request.app.state.db


# Use as an endpoint parameter type: `def endpoint(db: Db): ...`
Db = Annotated[Database, Depends(get_db)]
