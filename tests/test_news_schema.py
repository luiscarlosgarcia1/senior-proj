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


def columns(path, table):
    with closing(sqlite3.connect(path)) as connection:
        return [row[1] for row in connection.execute(f"pragma table_info({table})")]


def test_copies_and_rejects_are_tables_with_the_whole_story_plus_why(tmp_path):
    path = tmp_path / "db.sqlite3"
    with open_database(path):
        pass

    story = columns(path, "news_articles")
    assert columns(path, "news_article_copies") == story + ["article_id", "reason"]
    assert columns(path, "news_rejected") == story + ["reason"]


def test_copies_and_rejects_can_be_filled_and_replaced(tmp_path):
    path = tmp_path / "db.sqlite3"
    copy = NEWS[0] | {"id": "copy-1", "article_id": NEWS[1]["id"], "reason": "same_story"}
    rejected = NEWS[0] | {"id": "rejected-1", "reason": "bad_date"}

    with open_database(path) as connection:
        replace_table(connection, "news_article_copies", [copy])
        replace_table(connection, "news_rejected", [rejected])
    with open_database(path) as connection:
        replace_table(connection, "news_rejected", [])

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("select id, article_id, reason from news_article_copies").fetchall() == [("copy-1", NEWS[1]["id"], "same_story")]
        assert connection.execute("select count(*) from news_rejected").fetchone()[0] == 0
