"""Pipeline: layer_meta.py describes how each layer appears in the layer panel."""

from layer_meta import LAYER_META

GROUPS = {"base", "hazard", "works", "evidence", "projects"}
SHAPES = {"poly", "dash", "line", "dot", "fema", "ring", "sq", "sqf", "dia", "diaf", "ramp"}
COLORS = {"nfhl", "firm", "twdb", "drain", "infra", "city", "hdrain", "bridge", "mapped", "photos",
          "fema", "nws", "proj", "sfp", "claims", "county", "sev-high", "warn"}


def test_every_layer_has_panel_fields():
    for layer_id, meta in LAYER_META.items():
        assert meta["group"] in GROUPS, layer_id
        assert meta["short_label"], layer_id
        assert meta["panel_row"], layer_id
        assert meta["legend"]["shape"] in SHAPES, layer_id
        assert meta["legend"]["color"] in COLORS, layer_id
        assert isinstance(meta.get("parts", []), list), layer_id


def test_groups_follow_the_design():
    by_group = {}
    for layer_id, meta in LAYER_META.items():
        by_group.setdefault(meta["group"], []).append(layer_id)

    assert by_group["base"] == ["county-boundaries"]
    assert set(by_group["hazard"]) == {"fema-nfhl", "hidalgo-firm-1981", "twdb-cursory-1in100", "twdb-cursory-1in500"}
    assert set(by_group["works"]) == {"waterways", "flood-infrastructure", "city-drainage", "hcdd1-drainage", "overture-bridges"}
    assert set(by_group["evidence"]) == {
        "hcdd1-flood-extents", "hcdd1-flood-photos", "fema-flood-photos", "nws-flood-reports", "nfip-claims-by-tract"}
    assert set(by_group["projects"]) == {"hcdd1-bond-projects", "flood-projects"}


def test_twdb_layers_share_a_row():
    one, two = LAYER_META["twdb-cursory-1in100"], LAYER_META["twdb-cursory-1in500"]

    assert one["panel_row"] == two["panel_row"] == "twdb"
    assert (one["short_label"], two["short_label"]) == ("1% annual chance", "0.2% annual chance")


def test_photo_parts_filters():
    parts = {p["id"]: p for p in LAYER_META["hcdd1-flood-photos"]["parts"]}

    assert parts["photos"]["label"] == "Photos you can open"
    assert parts["photos"]["filter"] == ["has", "photo_url"]
    assert parts["locations"]["label"] == "Photo locations only"
    assert parts["locations"]["filter"] == ["!", ["has", "photo_url"]]
