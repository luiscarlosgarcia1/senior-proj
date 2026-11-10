"""Pipeline: pipeline/news_clean.py — tidying, checking and merging the stories before they reach news_articles.

`clean` is a pure function of the stories it is given, so running it again on its own output changes nothing.
Stories it removes are not lost: copies of a story another outlet already told, and stories that fail a check,
come back with their whole row so the rules can be changed later without a new crawl.
"""

from datetime import date

import news_clean
import pytest
from news_clean import OWN_NAME_TAILS, as_row, clean
from news_outlets import default_sources

TODAY = date(2026, 11, 9)


def row(**changes):
    base = {
        "id": "a1", "publisher": "KRGV Channel 5 News", "source_url": "https://krgv.test/a",
        "headline": "Flooding closes streets in McAllen", "published_at": "2020-07-26T12:00:00Z",
        "excerpt": "Several streets are closed.", "county": "hidalgo", "counties": "hidalgo", "city": "McAllen",
        "places": None, "matched_terms": "flooding", "topics": "flood", "kind": "news", "headline_from": "page",
        "retrieved_at": "2026-11-09T00:00:00Z",
    }
    return base | changes


def run(*rows):
    return clean(list(rows), today=TODAY)


# ---- tidying the text ----

def test_html_codes_left_in_a_headline_or_excerpt_are_decoded_and_spaces_collapsed():
    (kept,) = run(row(headline="Flood &amp; drainage  plan\n for Weslaco", excerpt="Residents pledge&hellip; more to come &#8212; officials said")).kept

    assert kept["headline"] == "Flood & drainage plan for Weslaco"
    assert kept["excerpt"] == "Residents pledge… more to come — officials said"


@pytest.mark.parametrize("publisher, tail", [
    ("Fox RGV (KFXV)", " | FOX RGV"),
    ("Rio Grande Guardian", " - Rio Grande Guardian"),
    ("City of Pharr", " – City Of Pharr"),
    ("The Texas Tribune", " | The Texas Tribune"),
])
def test_an_outlets_own_name_is_cut_from_the_end_of_its_headline(publisher, tail):
    (kept,) = run(row(publisher=publisher, headline="Hidalgo County flood advisory" + tail)).kept

    assert kept["headline"] == "Hidalgo County flood advisory"


def test_a_tail_that_is_not_the_outlets_own_name_stays():
    (kept,) = run(row(publisher="KRGV Channel 5 News", headline="Facing the Fury - How to clean your flood-damaged home")).kept
    (other,) = run(row(publisher="KRGV Channel 5 News", headline="Road closures in McAllen | FOX RGV")).kept  # another outlet's name

    assert kept["headline"].endswith("How to clean your flood-damaged home")
    assert other["headline"] == "Road closures in McAllen | FOX RGV"


def test_every_outlet_that_has_a_tail_rule_is_a_real_publisher():
    publishers = {source.publisher for source in default_sources()}

    assert set(OWN_NAME_TAILS) <= publishers


def test_tidying_never_changes_the_meaning_only_the_form():
    original = row(headline="Mission  council votes on drainage", excerpt="The council voted 4-1 on the plan.")

    (kept,) = run(original).kept

    assert kept["headline"] == "Mission council votes on drainage" and kept["excerpt"] == original["excerpt"]


# ---- stories that are not about water ----

def test_a_story_that_matched_only_a_place_name_is_rejected_with_its_whole_row():
    story = row(id="r1", headline="Rio Grande City woman sentenced for meth", matched_terms="rio grande", topics="water_system")

    result = run(story)

    assert result.kept == []
    (rejected,) = result.rejected
    assert rejected["reason"] == "place_name_only" and rejected["id"] == "r1" and rejected["matched_terms"] == "rio grande"
    assert rejected["source_url"] == story["source_url"] and rejected["headline"] == story["headline"]


def test_a_place_name_is_dropped_from_a_story_that_also_has_a_real_water_word():
    (kept,) = run(row(matched_terms="rio grande,flooding", topics="water_system,flood")).kept

    assert kept["matched_terms"] == "flooding" and kept["topics"] == "flood"  # the river's name was the only water_system word


def test_a_place_name_does_not_take_away_a_topic_a_real_word_also_gives():
    (kept,) = run(row(matched_terms="rio grande,levee,flooding", topics="water_system,flood")).kept

    assert kept["matched_terms"] == "levee,flooding" and set(kept["topics"].split(",")) == {"water_system", "flood"}


def test_a_story_with_no_such_place_name_keeps_its_terms_and_topics_exactly():
    story = row(matched_terms="boil water,drainage", topics="water_system,water")

    (kept,) = run(story).kept

    assert kept["matched_terms"] == story["matched_terms"] and kept["topics"] == story["topics"]


# ---- dates and headlines ----

@pytest.mark.parametrize("stamp", ["2026-12-25T00:00:00Z", "1989-12-31T00:00:00Z", "not a date", ""])
def test_a_date_in_the_future_before_1990_or_unreadable_is_rejected(stamp):
    result = run(row(published_at=stamp))

    assert result.kept == [] and [r["reason"] for r in result.rejected] == ["bad_date"]


def test_a_bare_date_and_tomorrow_are_fine():
    result = run(row(id="a", published_at="2020-07-26"), row(id="b", source_url="https://x/b", headline="Another flood story in Weslaco", published_at="2026-11-10T01:00:00Z"))

    assert len(result.kept) == 2


def test_a_headline_with_almost_nothing_in_it_is_rejected():
    result = run(row(headline="Flood | FOX RGV", publisher="Fox RGV (KFXV)"))

    assert result.kept == [] and [r["reason"] for r in result.rejected] == ["short_headline"]


# ---- repeated site-wide descriptions ----

def test_a_description_a_site_puts_on_three_or_more_stories_is_not_about_any_of_them():
    boilerplate = "Texas Public Radio is updating information on COVID-19 in the Rio Grande Valley."
    stories = [row(id=f"t{n}", source_url=f"https://tpr.test/{n}", headline=f"Weslaco flood story number {n}", excerpt=boilerplate) for n in range(3)]
    stories.append(row(id="t9", source_url="https://tpr.test/9", headline="Mission drainage vote tonight", excerpt="Two stories share this.", published_at="2020-01-01T00:00:00Z"))
    stories.append(row(id="t10", source_url="https://tpr.test/10", headline="Pharr drainage vote on Tuesday", excerpt="Two stories share this.", published_at="2020-01-02T00:00:00Z"))

    kept = {r["id"]: r for r in run(*stories).kept}

    assert all(kept[f"t{n}"]["excerpt"] is None for n in range(3))
    assert kept["t9"]["excerpt"] == "Two stories share this." == kept["t10"]["excerpt"]  # twice is a coincidence


def test_the_same_description_on_different_outlets_is_not_counted_together():
    stories = [row(id=f"p{n}", publisher=f"Outlet {n}", source_url=f"https://o{n}.test/a", headline=f"Different flood headline {n} Weslaco", excerpt="Shared wire copy.") for n in range(3)]

    assert all(r["excerpt"] == "Shared wire copy." for r in run(*stories).kept)


# ---- the same story twice ----

def test_the_same_headline_within_three_days_is_one_story_and_the_other_is_kept_as_a_copy():
    first = row(id="a1", publisher="Border Report (Nexstar)", source_url="https://br.test/a", published_at="2020-07-26T12:00:00Z")
    second = row(id="a2", publisher="ValleyCentral (KVEO, KGBT)", source_url="https://vc.test/a", published_at="2020-07-28T09:00:00Z")

    result = run(second, first)

    assert [r["id"] for r in result.kept] == ["a1"]
    (copy,) = result.copies
    assert copy["id"] == "a2" and copy["article_id"] == "a1" and copy["reason"] == "same_story"
    assert copy["publisher"] == "ValleyCentral (KVEO, KGBT)" and copy["source_url"] == "https://vc.test/a"  # still cited


def test_a_headline_that_is_the_publishers_own_beats_one_made_from_an_address():
    made = row(id="a1", published_at="2020-07-26T08:00:00Z", headline_from="address", excerpt=None, headline="Flooding Closes Streets In Mcallen")
    theirs = row(id="a2", source_url="https://x/b", published_at="2020-07-27T08:00:00Z", headline="Flooding closes streets in McAllen")

    result = run(made, theirs)

    assert [r["id"] for r in result.kept] == ["a2"] and [r["article_id"] for r in result.copies] == ["a2"]


def test_with_nothing_to_choose_between_them_the_earlier_one_is_kept():
    early = row(id="b", published_at="2020-07-26T08:00:00Z")
    late = row(id="a", source_url="https://x/b", published_at="2020-07-27T08:00:00Z")

    assert [r["id"] for r in run(late, early).kept] == ["b"]


def test_the_same_headline_more_than_three_days_apart_is_two_stories():
    advisory = "Flood advisory issued for parts of Cameron County"
    result = run(row(id="a", headline=advisory, published_at="2020-07-26T08:00:00Z"),
                 row(id="b", source_url="https://x/b", headline=advisory, published_at="2020-08-30T08:00:00Z"))

    assert sorted(r["id"] for r in result.kept) == ["a", "b"] and result.copies == []


def test_punctuation_and_case_do_not_make_two_headlines_different():
    result = run(row(id="a", headline="Flooding closes streets in McAllen!"),
                 row(id="b", source_url="https://x/b", headline="FLOODING CLOSES STREETS IN MCALLEN", published_at="2020-07-26T13:00:00Z"))

    assert len(result.kept) == 1 and len(result.copies) == 1


def test_three_copies_in_a_row_all_point_at_the_one_kept():
    stories = [row(id=f"s{n}", source_url=f"https://x/{n}", published_at=f"2020-07-2{6 + n}T08:00:00Z") for n in range(3)]

    result = run(*stories)

    assert [r["id"] for r in result.kept] == ["s0"] and sorted(r["article_id"] for r in result.copies) == ["s0", "s0"]


# ---- the shape of the result ----

def test_kept_rows_have_the_same_columns_as_the_stories_that_came_in_newest_first():
    older = row(id="a", published_at="2019-01-01T00:00:00Z")
    newer = row(id="b", source_url="https://x/b", headline="Brownsville drainage project begins", published_at="2021-01-01T00:00:00Z")

    result = run(older, newer)

    assert [r["id"] for r in result.kept] == ["b", "a"]
    assert all(set(r) == set(older) for r in result.kept)


def test_copies_and_rejects_carry_the_whole_story_plus_why():
    result = run(row(id="a"), row(id="b", source_url="https://x/b", published_at="2020-07-27T00:00:00Z"),
                 row(id="c", source_url="https://x/c", headline="Rio Grande Valley man jailed", matched_terms="rio grande", topics="water_system"))

    (copy,) = result.copies
    (rejected,) = result.rejected
    assert set(copy) == set(row()) | {"article_id", "reason"} and set(rejected) == set(row()) | {"reason"}


def test_the_input_is_left_alone():
    story = row(headline="Flood &amp; drainage plan")
    snapshot = dict(story)

    run(story)

    assert story == snapshot


def test_running_clean_on_its_own_output_changes_nothing():
    stories = [
        row(id="a", headline="Flooding closes streets in McAllen!"),
        row(id="b", source_url="https://x/b", headline="Flooding closes streets in McAllen", published_at="2020-07-27T00:00:00Z"),
        row(id="c", source_url="https://x/c", headline="Rio Grande Valley man jailed", matched_terms="rio grande", topics="water_system"),
        row(id="d", source_url="https://x/d", headline="Pharr drainage vote on Tuesday | FOX RGV", publisher="Fox RGV (KFXV)", published_at="2021-03-01T00:00:00Z"),
    ]
    first = run(*stories)

    again = run(*first.kept, *map(as_row, first.copies), *map(as_row, first.rejected))

    assert again.kept == first.kept and again.copies == first.copies and again.rejected == first.rejected


def test_as_row_drops_only_the_extra_columns():
    stored = row(id="a") | {"article_id": "z", "reason": "same_story"}

    assert as_row(stored) == row(id="a")
    assert as_row(row(id="a")) == row(id="a")


def test_the_place_names_that_do_not_count_are_the_matchers():
    import news_match

    assert news_clean.PLACE_NAME_TERMS == news_match.PLACE_NAME_TERMS == frozenset({"rio grande", "rio bravo"})
