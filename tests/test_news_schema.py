"""Pipeline: the news_articles table (pipeline/database.py) and its fixture rows."""

import sqlite3
from contextlib import closing

from database import open_database, replace_table
from fixture_db import NEWS


def test_news_articles_table_is_created_and_replaceable(tmp_path):
    path = tmp_path / "db.sqlite3"

    with open_database(path) as connection:
        replace_table(connection, "news_articles", NEWS)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("select count(*) from news_articles").fetchone()[0] == 3

    with open_database(path) as connection:
        replace_table(connection, "news_articles", [])
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("select count(*) from news_articles").fetchone()[0] == 0
