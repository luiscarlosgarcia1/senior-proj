"""Read-only access to the central database.

The app never writes: connections open the file read-only and refuse writes
even through a pragma. The live-alert refresher is the only writer, and the
database runs in WAL mode, so reads never wait on it. Before the pipeline has
built the database, queries return None (`rows`) or nothing (`app_rows`) and
the file is not created.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import Request


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = 1")
        return connection

    def rows(self, query: str, parameters: tuple | dict = ()) -> list[dict] | None:
        """Rows of a query as dicts, or None when the database hasn't been built yet."""
        if not self.exists:
            return None
        # closing(): sqlite3's own context manager commits but never closes the file.
        with closing(self._connect()) as connection:
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
