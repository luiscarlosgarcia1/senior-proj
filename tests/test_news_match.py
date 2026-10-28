"""Pipeline: pipeline/news_match.py — which news stories are about flooding in the four counties."""

from news_match import match_story, mentions_flood, places_in, slug_may_be_flood


def test_flood_story_with_city_matches():
    match = match_story("Flash flooding closes streets in McAllen", "")

    assert match.counties == ("hidalgo",)
    assert match.city == "McAllen"
    assert {"flash flood", "flooding"} & set(match.terms)


def test_two_counties_ordered_by_first_mention():
    match = match_story("Heavy rain floods Harlingen, McAllen", "")

    assert match.counties == ("cameron", "hidalgo")
    assert match.city == "Harlingen"


def test_county_name_without_city():
    match = match_story("Flood warning for Hidalgo County", "")

    assert match.counties == ("hidalgo",)
    assert match.city is None


def test_description_can_supply_the_place():
    match = match_story("Streets underwater after storm", "Floodwater covered roads across Cameron County.")

    assert match.counties == ("cameron",)


def test_no_flood_term_is_dropped():
    assert match_story("Weslaco council approves budget", "") is None


def test_no_place_is_dropped():
    assert match_story("Flood insurance rates rise nationwide", "") is None


def test_rio_grande_valley_is_not_rio_grande_city():
    assert match_story("Rio Grande Valley braces for flooding", "") is None


def test_rio_grande_city_is_starr():
    assert match_story("Flooding closes roads in Rio Grande City", "").counties == ("starr",)


def test_lowercase_mission_is_not_the_city():
    assert match_story("Mission statement on flood plan", "") is None
    assert match_story("Flooding hits Mission", "").counties == ("hidalgo",)


def test_spanish_flood_story_matches():
    assert match_story("Inundaciones afectan a Brownsville", "").counties == ("cameron",)


def test_slug_prefilter():
    assert slug_may_be_flood("https://www.krgv.com/news/flash-flooding-closes-streets-in-mcallen")
    assert not slug_may_be_flood("https://www.krgv.com/news/wreaths-across-america-project-in-need-of-volunteers")


def test_places_in_finds_streets():
    found = places_in("Water over Expressway 83 near Ware Road")

    assert "Expressway 83" in found
    assert "Ware Road" in found


def test_places_in_nothing_found():
    assert places_in("Rain fell all night") is None


def test_mentions_flood():
    assert mentions_flood("City of Pharr Prevents Future Flooding with Trash Pick-Up Event")
    assert not mentions_flood("Wreaths Across America Project in Need of Volunteers")
