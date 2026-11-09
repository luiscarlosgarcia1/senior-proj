"""Chat: the read-only query tool the model is given (rgv_flood/chat/sqltool.py)."""

import re
import sqlite3
import time
from contextlib import closing

import pytest

from rgv_flood.chat.sqltool import QueryRefused, describe_database, run_select
from rgv_flood.db import Database


def counts(path):
    with closing(sqlite3.connect(path)) as connection:
        return [connection.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("flood_events", "nfip_claims", "layers", "weather_observations")]


def test_select_returns_columns_and_rows(fixture_db):
    result = run_select(Database(fixture_db), "select county, count(*) as n from nfip_claims group by county order by county")

    assert result == {"columns": ["county", "n"], "rows": [["hidalgo", 3], ["starr", 1]], "row_count": 2, "truncated": False}


def test_with_query_is_allowed(fixture_db):
    result = run_select(Database(fixture_db), "with x as (select 1 as a) select a from x")

    assert result["rows"] == [[1]]


def test_a_trailing_semicolon_is_fine(fixture_db):
    assert run_select(Database(fixture_db), "select 1 as a;")["rows"] == [[1]]


def test_row_cap_marks_truncated(fixture_db):
    result = run_select(Database(fixture_db), "select * from weather_observations", row_cap=3)

    assert result["row_count"] == 3 and len(result["rows"]) == 3
    assert result["truncated"] is True


def test_cells_are_cut_and_blobs_are_summarized(fixture_db):
    db = Database(fixture_db)

    text = run_select(db, "select replace(hex(zeroblob(250)), '0', 'a') as t")["rows"][0][0]
    blob = run_select(db, "select geojson_gzip from layers limit 1")["rows"][0][0]

    assert len(text) == 300 and text.endswith("…")
    assert re.fullmatch(r"<blob, \d+ bytes>", blob)


@pytest.mark.parametrize("sql", [
    "insert into flood_events(id) values ('x')",
    "update flood_events set county = 'x'",
    "delete from flood_events",
    "drop table flood_events",
    "pragma writable_schema = 1",
    "attach database ':memory:' as m",
    "select 1; select 2",
    "select 1; drop table flood_events",
    "select 1 -- ; drop table flood_events\n; select 2",
    "select 1 /* hide */ ; delete from nfip_claims",
    "with t as (select 1) insert into flood_events(id) select 'x'",
    "select load_extension('x')",
    "",
    "   ",
])
def test_refuses_everything_that_is_not_one_select(fixture_db, sql):
    before = counts(fixture_db)

    with pytest.raises(QueryRefused):
        run_select(Database(fixture_db), sql)

    assert counts(fixture_db) == before


def test_a_semicolon_inside_a_string_or_comment_is_fine(fixture_db):
    result = run_select(Database(fixture_db), "select 'a;b' as v -- trailing; comment")

    assert result["rows"] == [["a;b"]]


def test_slow_query_is_stopped(fixture_db):
    slow = "with recursive c(x) as (select 1 union all select x + 1 from c where x < 1000000000) select count(*) from c"
    started = time.monotonic()

    with pytest.raises(QueryRefused, match="longer than"):
        run_select(Database(fixture_db), slow, seconds=0.2)

    assert time.monotonic() - started < 3


def test_sqlite_errors_come_back_as_text(fixture_db):
    with pytest.raises(QueryRefused, match="^SQL error:"):
        run_select(Database(fixture_db), "select nope from nfip_claims")


def test_unbuilt_database_is_refused(tmp_path):
    with pytest.raises(QueryRefused, match="not been built"):
        run_select(Database(tmp_path / "missing.sqlite3"), "select 1")


def test_describe_lists_tables_columns_counts_and_sources(fixture_db):
    described = describe_database(Database(fixture_db))

    tables = {table["name"]: table for table in described["tables"]}
    assert "year_of_loss" in [column["name"] for column in tables["nfip_claims"]["columns"]]
    assert tables["nfip_claims"]["rows"] == 4
    assert "noaa-storm-events" in [source["id"] for source in described["sources"]]
