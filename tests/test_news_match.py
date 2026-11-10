"""Pipeline: pipeline/news_match.py — which news stories are about flooding in the four counties."""

import pytest
from news_match import (
    has_valley_place,
    headline_from_slug,
    match_story,
    mentions_flood,
    places_in,
)


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


def test_rio_grande_valley_is_the_whole_region_not_rio_grande_city():
    match = match_story("Rio Grande Valley braces for flooding", "")

    assert match.counties == () and match.city is None  # a story about the whole Valley


def test_rio_grande_city_is_starr():
    assert match_story("Flooding closes roads in Rio Grande City", "").counties == ("starr",)


def test_lowercase_mission_is_not_the_city():
    assert match_story("Mission statement on flood plan", "") is None
    assert match_story("Flooding hits Mission", "").counties == ("hidalgo",)


def test_spanish_flood_story_matches():
    assert match_story("Inundaciones afectan a Brownsville", "").counties == ("cameron",)


def test_slug_prefilter():
    assert mentions_flood(headline_from_slug("https://www.krgv.com/news/flash-flooding-closes-streets-in-mcallen"))
    assert not mentions_flood(headline_from_slug("https://www.krgv.com/news/wreaths-across-america-project-in-need-of-volunteers"))


def test_places_in_finds_streets():
    found = places_in("Water over Expressway 83 near Ware Road")

    assert "Expressway 83" in found
    assert "Ware Road" in found


def test_places_in_nothing_found():
    assert places_in("Rain fell all night") is None


def test_mentions_flood():
    assert mentions_flood("City of Pharr Prevents Future Flooding with Trash Pick-Up Event")
    assert not mentions_flood("Wreaths Across America Project in Need of Volunteers")


# ---- everything about water, not only floods ----

@pytest.mark.parametrize("headline, topic", [
    ("Flash flooding closes streets in McAllen", "flood"),
    ("Downpour soaks Harlingen overnight", "rain"),
    ("Hurricane Hanna makes landfall near Port Mansfield", "storm"),
    ("Drought leaves Falcon Lake at record low near Roma", "drought"),
    ("Weslaco crews repair water main break", "water_system"),
    ("Boil water notice lifted in Edinburg", "water_system"),
    ("Hidalgo County drainage district clears ditches", "water_system"),
    ("Water rates rising in Brownsville", "water_system"),
    ("Water polo team wins in Mission this weekend", "water"),
    ("Inundaciones dejan calles bajo el agua en Brownsville", "flood"),
    ("Lluvias fuertes golpean Reynosa y McAllen", "rain"),
    ("Sequía preocupa a agricultores de Hidalgo County", "drought"),
])
def test_topics_cover_flood_rain_storm_drought_and_water_systems(headline, topic):
    match = match_story(headline, "")

    assert match is not None and topic in match.topics


def test_a_story_can_have_several_topics():
    match = match_story("Storm brings heavy rain and street flooding to Brownsville", "")

    assert {"storm", "rain", "flood"} <= set(match.topics)


@pytest.mark.parametrize("headline", [
    "Raiders beat Rainbow Warriors in Mission",  # rainbow, not rain
    "Hidalgo County approves budget",
    "Train derails near Harlingen",
    "McAllen restaurant serves sunset dinners",
])
def test_unrelated_stories_stay_out(headline):
    assert match_story(headline, "") is None


def test_the_valley_as_a_whole_is_a_place():
    for text in ("RGV flooding worsens", "Rain soaks the Valley", "Lower Rio Grande Valley under flood watch"):
        assert match_story(text, "").counties == ()


def test_silicon_valley_is_not_the_rio_grande_valley():
    assert match_story("Flood of tech layoffs hits Silicon Valley", "") is None


@pytest.mark.parametrize("place, county", [
    ("Los Fresnos", "cameron"), ("Santa Rosa", "cameron"), ("Palm Valley", "cameron"), ("Port Mansfield", "willacy"),
    ("Sullivan City", "hidalgo"), ("Peñitas", "hidalgo"), ("Palmhurst", "hidalgo"), ("Sharyland", "hidalgo"),
    ("Boca Chica", "cameron"), ("Olmito", "cameron"), ("La Villa", "hidalgo"), ("Rangerville", "cameron"),
])
def test_more_valley_towns_are_known(place, county):
    assert match_story(f"Flooding reported in {place}", "").counties == (county,)


def test_county_names_in_spanish():
    assert match_story("Inundaciones en el Condado de Hidalgo", "").counties == ("hidalgo",)


# ---- stories known only by their address ----

@pytest.mark.parametrize("url, expected", [
    ("https://www.valleycentral.com/news/local-news/flash-flooding-closes-streets-in-mcallen/", "Flash Flooding Closes Streets In McAllen"),
    ("https://riograndeguardian.com/stories/peterson-visits-rgv,6491", "Peterson Visits RGV"),
    ("https://www.krgv.com/news/city-of-pharr-prevents-future-flooding.html", "City Of Pharr Prevents Future Flooding"),
    ("https://example.test/2020/07/25/water-main-break-in-san-benito-12345678/", "Water Main Break In San Benito"),
])
def test_headline_from_slug(url, expected):
    assert headline_from_slug(url) == expected


def test_a_story_known_only_by_its_address_can_be_matched():
    headline = headline_from_slug("https://www.valleycentral.com/news/local-news/street-flooding-in-los-fresnos/")

    assert match_story(headline, "").counties == ("cameron",)


@pytest.mark.parametrize("text, strict, expected", [
    ("Street Flooding In Harlingen", True, True),
    ("Street Flooding In Mission", True, False),  # a common word: only trusted with more
    ("Street Flooding In Mission", False, True),
    ("Rgv Rain Totals", True, True),
    ("Flooding Closes Roads In Laredo", True, False),
    ("Hidalgo County Drainage Plan", True, True),
])
def test_valley_place_in_a_headline(text, strict, expected):
    assert has_valley_place(headline_from_slug(text.replace(" ", "-")), strict=strict) is expected


def test_water_words_widen_the_address_prefilter():
    assert mentions_flood(headline_from_slug("https://x.test/news/boil-water-notice-for-edinburg"))
    assert mentions_flood(headline_from_slug("https://x.test/news/drought-hits-farmers"))
    assert not mentions_flood(headline_from_slug("https://x.test/news/football-team-wins"))


# ---- the river's name in a place name is not a water word ----

@pytest.mark.parametrize("text", [
    "Rio Grande Valley man arrested", "Smugglers drive load into the Rio Grande", "Rio Grande City woman sentenced",
    "UTRGV baseball: Rio Grande Valley sports roundup", "Hallan cuerpo en el Rio Bravo",
])
def test_a_place_name_with_the_rivers_name_is_not_a_water_word(text):
    assert not mentions_flood(text)


def test_such_a_story_has_no_match_even_though_it_names_a_valley_place():
    assert match_story("Rio Grande City woman sentenced to five years", "") is None
    assert match_story("Smugglers near McAllen drive load into the Rio Grande", "") is None


def test_the_river_still_counts_when_the_story_has_a_real_water_word():
    assert mentions_flood("Rio Grande levee breach near Hidalgo")
    match = match_story("Flooding in Rio Grande City", "")
    assert match.topics == ("flood",) and "rio grande" not in match.terms


def test_the_place_names_that_do_not_count_are_listed():
    from news_match import PLACE_NAME_TERMS

    assert PLACE_NAME_TERMS == frozenset({"rio grande", "rio bravo"})
