from rgv_flood.severity import MAPPING, RELATIVE_CLASSES, relative_class_for


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
