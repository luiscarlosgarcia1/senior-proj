"""The two things the chatbot's model may do with the database: describe it, and
run one read-only SELECT.

The app's own database connection is never handed to the model. Each query gets
a fresh connection opened read-only, with an authorizer that allows nothing but
reading, a time limit, and the results cut down (rows, cell length, binary
data) before they go back into the conversation.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing

from rgv_flood.db import Database

ROW_CAP = 200
CELL_CAP = 300
QUERY_SECONDS = 5.0
DESCRIBE_SECONDS = 300.0

# What a SELECT needs and nothing else (no writes, no ATTACH, no PRAGMA).
_ALLOWED_ACTIONS = frozenset({
    sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE,
})
_DENIED_FUNCTIONS = frozenset({"load_extension"})

_describe_cache: dict[tuple, tuple[float, dict]] = {}


class QueryRefused(Exception):
    """The query was not run. The message is safe to show the model."""


def _authorizer(action, arg1, arg2, _database, _source) -> int:
    if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() in _DENIED_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _skeleton(sql: str) -> str:
    """`sql` with string literals, quoted names and comments blanked out, so a `;`
    that is really inside one of them is not mistaken for a statement break."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        char = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif char in "'\"`":
            i += 1
            while i < n:
                if sql[i] == char:
                    if sql.startswith(char, i + 1):  # a doubled quote is a quote inside the text
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            out.append(" ")
        elif char == "[":
            end = sql.find("]", i)
            i = n if end == -1 else end + 1
            out.append(" ")
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _check_single_select(sql: str) -> None:
    skeleton = _skeleton(sql).strip()
    while skeleton.endswith(";"):
        skeleton = skeleton[:-1].rstrip()
    if not skeleton:
        raise QueryRefused("Send one SELECT statement.")
    if ";" in skeleton:
        raise QueryRefused("Only one statement at a time: send a single SELECT.")
    if skeleton.split(None, 1)[0].lower() not in ("select", "with"):
        raise QueryRefused("Only SELECT queries are allowed (the database is read-only).")


def _cell(value, cell_cap: int):
    if isinstance(value, bytes):
        return f"<blob, {len(value)} bytes>"
    if isinstance(value, str) and len(value) > cell_cap:
        return value[: cell_cap - 1] + "…"
    return value


def _read_only(db: Database) -> sqlite3.Connection:
    if not db.exists:
        raise QueryRefused("The database has not been built yet.")
    return sqlite3.connect(f"file:{db.path.as_posix()}?mode=ro", uri=True)


def run_select(
    db: Database, sql: str, *, row_cap: int = ROW_CAP, cell_cap: int = CELL_CAP, seconds: float = QUERY_SECONDS
) -> dict:
    """Run one read-only SELECT and return `{columns, rows, row_count, truncated}`."""
    _check_single_select(sql)
    connection = _read_only(db)
    deadline = time.monotonic() + seconds
    timed_out = False

    def stop_when_late() -> int:
        nonlocal timed_out
        timed_out = time.monotonic() > deadline
        return 1 if timed_out else 0

    with closing(connection):
        connection.set_authorizer(_authorizer)
        connection.set_progress_handler(stop_when_late, 1000)
        try:
            cursor = connection.execute(sql)
            fetched = cursor.fetchmany(row_cap + 1)
            columns = [column[0] for column in cursor.description or []]
        except sqlite3.Error as error:
            if timed_out:
                raise QueryRefused(f"The query took longer than {seconds:g} seconds; make it more specific.") from None
            raise QueryRefused(f"SQL error: {error}") from None
    rows = [[_cell(value, cell_cap) for value in row] for row in fetched[:row_cap]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": len(fetched) > row_cap}


def describe_database(db: Database) -> dict:
    """Every table with its columns and row count, and the `data_sources` rows (who
    published each dataset and when it was downloaded). Kept for a few minutes and
    refreshed as soon as a new build replaces the file."""
    if not db.exists:
        raise QueryRefused("The database has not been built yet.")
    key = (str(db.path), db.path.stat().st_mtime_ns)
    cached = _describe_cache.get(key)
    if cached and time.monotonic() - cached[0] < DESCRIBE_SECONDS:
        return cached[1]
    with closing(_read_only(db)) as connection:
        connection.row_factory = sqlite3.Row
        names = [row["name"] for row in connection.execute(
            "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name")]
        tables = [{
            "name": name,
            "rows": connection.execute(f'select count(*) from "{name}"').fetchone()[0],
            "columns": [{"name": column["name"], "type": column["type"]}
                        for column in connection.execute("select name, type from pragma_table_info(?)", (name,))],
        } for name in names]
        sources = ([dict(row) for row in connection.execute("select * from data_sources order by id")]
                   if "data_sources" in names else [])
    described = {"tables": tables, "sources": sources}
    _describe_cache[key] = (time.monotonic(), described)
    return described
