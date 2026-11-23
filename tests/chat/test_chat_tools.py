"""Chat: the fixed, read-only data tools the model may call (fixture database only)."""

import pytest
from fixture_db import add_chat_fixture, build_fixture_database

from rgv_flood.chat.sqltool import QueryRefused, run_bound
from rgv_flood.chat.tools import ToolError, find_place, normalize_county
from rgv_flood.db import Database


@pytest.fixture()
def chat_db(fixture_db):
    return Database(add_chat_fixture(fixture_db))


def test_tool_error_is_a_refusal():
    assert issubclass(ToolError, QueryRefused)


def test_normalize_county():
    assert normalize_county("Hidalgo County") == "hidalgo"
    assert normalize_county("  CAMERON ") == "cameron"
    with pytest.raises(ToolError, match="cameron, hidalgo, starr, willacy"):
        normalize_county("hidalgo' OR 1=1 --")


def test_run_bound_binds_parameters(chat_db):
    out = run_bound(chat_db, "select count(*) as n from nfip_claims where county = ?", ("hidalgo' or '1'='1",))
    assert out["rows"] == [[0]]
    assert run_bound(chat_db, "select count(*) from nfip_claims where county = ?", ("hidalgo",))["rows"] == [[3]]


def test_find_place_exact(chat_db):
    r = find_place(chat_db, "edinburg")
    assert r["ambiguous"] is False
    m = r["matches"][0]
    assert m["county"] == "hidalgo" and m["kind"] == "city"
    assert set(m["tracts"]) == {"48215020100", "48215020200"}
    assert set(m["tract_vintages"]) == {2010, 2023}
    assert r["from"] == "places, place_tracts"


def test_find_place_accent_and_alias(chat_db):
    assert find_place(chat_db, "Penitas")["matches"][0]["name"] == "Peñitas"
    assert find_place(chat_db, "PEÑITAS")["matches"][0]["name"] == "Peñitas"


def test_find_place_exact_beats_prefix(chat_db):
    r = find_place(chat_db, "mission")
    assert [m["name"] for m in r["matches"]] == ["Mission"] and r["ambiguous"] is False


def test_find_place_prefix_can_be_ambiguous(chat_db):
    r = find_place(chat_db, "ed")
    assert r["ambiguous"] is True
    assert {m["name"] for m in r["matches"]} == {"Edinburg", "Edcouch"}
    assert find_place(chat_db, "mis")["matches"][0]["name"] == "Mission"  # name prefix only, not "La Mission"


def test_find_place_no_match(chat_db):
    r = find_place(chat_db, "Atlantis")
    assert r["matches"] == [] and "county" in r["hint"]


def test_find_place_without_places_table(tmp_path):
    db = Database(build_fixture_database(tmp_path / "old.sqlite3"))
    with pytest.raises(ToolError, match="Places are not built yet"):
        find_place(db, "Edinburg")
