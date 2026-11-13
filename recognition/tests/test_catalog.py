import pytest

from reco.catalog import Catalogue, CatalogueError, CatalogueItem, load_catalogue

#: Role A, Rules v1.0. If A ships a new catalogue this test fails on purpose:
#: refresh data/supported_items.csv, update data/README.md and this hash.
EXPECTED_SHA256 = "41d7b47787775002b34dbd35f9a477e64e4c39f536ecd6c06ea517b7dcd19858"


def test_catalogue_loads_role_a_items():
    cat = load_catalogue()
    assert len(cat) == 16
    assert cat.resolve("plastic_beverage_bottle") == "plastic_beverage_bottle"
    assert cat.name_of("plastic_beverage_bottle") == "Plastic beverage bottle"


def test_catalogue_hash_pins_role_a_version():
    assert load_catalogue().sha256 == EXPECTED_SHA256


def test_resolve_accepts_ids_names_and_aliases():
    cat = load_catalogue()
    for raw in ("plastic_beverage_bottle", "Plastic beverage bottle", "PET drink bottle", "plastic water bottle"):
        assert cat.resolve(raw) == "plastic_beverage_bottle", raw
    assert cat.resolve("glass soda bottle") == "glass_beverage_bottle"
    assert cat.resolve("tin food can") == "metal_food_can"


def test_resolve_is_strict_no_fuzzy_guessing():
    cat = load_catalogue()
    # plausible but not a listed alias: must NOT silently become a match
    assert cat.resolve("plastic bottle") is None
    assert cat.resolve("battery") is None
    assert cat.resolve("") is None


def test_resolve_many_dedupes_and_filters():
    cat = load_catalogue()
    got = cat.resolve_many(["glass_beverage_bottle", "glass soda bottle", "battery", ""])
    assert got == ["glass_beverage_bottle"]


def test_prompt_block_lists_every_id():
    cat = load_catalogue()
    block = cat.prompt_block()
    assert block.startswith("item_id | item_name")
    for item_id in cat.ids():
        assert item_id in block
    assert len(block.splitlines()) == len(cat) + 1


def test_material_vocabulary():
    vocab = load_catalogue().material_vocabulary()
    assert "Plastic" in vocab and "Glass" in vocab and "Food organics" in vocab


def test_missing_catalogue_raises_with_hint(tmp_path):
    with pytest.raises(CatalogueError) as info:
        load_catalogue(tmp_path / "nope.csv")
    assert "RECO_CATALOGUE" in str(info.value)


def test_duplicate_ids_rejected(tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text(
        "item_id,item_name,aliases,material,scope\n"
        "a,Item A,,Plastic,scope\n"
        "a,Item B,,Glass,scope\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogueError):
        load_catalogue(path)


def test_missing_columns_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("item_id,item_name\nx,Item X\n", encoding="utf-8")
    with pytest.raises(CatalogueError):
        load_catalogue(path)


def test_index_covers_every_alias():
    cat = load_catalogue()
    for item in cat.items.values():
        for alias in item.aliases:
            assert cat.resolve(alias) == item.item_id


def test_catalogue_item_is_frozen():
    item = CatalogueItem(item_id="x", item_name="X", aliases=(), material="Plastic", scope="s")
    with pytest.raises(Exception):
        item.item_id = "y"  # type: ignore[misc]
