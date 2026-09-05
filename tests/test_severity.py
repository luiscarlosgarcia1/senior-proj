import pytest

from rgv_flood.severity import (
    MAPPING,
    RELATIVE_CLASSES,
    classify_fema_zone,
    relative_class_for,
)


def test_every_mapping_entry_uses_a_known_class():
    for entry in MAPPING:
        assert entry["relative_class"] in RELATIVE_CLASSES
        assert entry["rationale"].strip()


def test_fema_ae_is_high():
    assert relative_class_for("FEMA NFHL", "AE") == "high"


def test_unmapped_category_falls_back_to_uncategorized():
    assert relative_class_for("FEMA NFHL", "made-up") == "uncategorized"
    assert relative_class_for("unknown source", "AE") == "uncategorized"


def test_historic_hidalgo_map_is_never_force_compared():
    assert (
        relative_class_for("Hidalgo County DD No. 1 digitized 1981 map", "Flood zone")
        == "uncategorized"
    )


@pytest.mark.parametrize(
    ("zone", "subty", "expected"),
    [
        ("A", None, "high"),
        ("AE", None, "high"),
        ("AE", "FLOODWAY", "high"),
        ("AH", None, "high"),
        ("AO", None, "high"),
        ("A23", None, "high"),
        ("VE", None, "high"),
        ("V13", None, "high"),
        ("B", None, "moderate"),
        ("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD", "moderate"),
        ("X", "AREA OF MINIMAL FLOOD HAZARD", "low"),
        ("X", None, "low"),
        ("C", None, "low"),
        ("OPEN WATER", None, "uncategorized"),
        ("", None, "uncategorized"),
        (None, None, "uncategorized"),
        ("D", None, "uncategorized"),
    ],
)
def test_classify_fema_zone(zone, subty, expected):
    assert classify_fema_zone(zone, subty) == expected


def test_classify_fema_zone_is_case_and_whitespace_insensitive():
    assert classify_fema_zone(" ae ", " floodway ") == "high"


def test_legacy_firm_letters_classify_like_modern():
    # Hidalgo's 1981 FIRM uses B (shaded X) and C (X) alongside AE/AH.
    assert classify_fema_zone("B") == "moderate"
    assert classify_fema_zone("C") == "low"
    assert classify_fema_zone("AE") == "high"
