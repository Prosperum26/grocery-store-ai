from src.schemas.recipe_dto import Product
from src.services.recipe_service import build_basket, pack_hint


def product(pack_size, pack_unit):
    return Product(catalog_id="CAT-1", name="x", category=None, pack_size=pack_size, pack_unit=pack_unit)


def line(ingredient, kind, cid, quantity=None, unit=None, status="da_ghep", alternatives=()):
    return {"ingredient": ingredient, "kind": kind, "raw_text": f"{ingredient} {quantity or ''}{unit or ''}", "quantity": quantity,
            "unit": unit, "status": status,
            "match": {"catalog_id": cid, "alternatives": [{"catalog_id": a, "product_name": a} for a in alternatives]} if status == "da_ghep" else None}


CATALOG = {c: {"catalog_id": c, "name": f"SP {c}", "category": "Củ, quả", "pack_size": s, "pack_unit": u}
           for c, s, u in [("CAT-1", 500, "g"), ("CAT-2", 1, "kg"), ("CAT-3", None, None), ("CAT-4", 250, "ml")]}


def test_pack_hint_rounds_up_when_units_compatible():
    assert pack_hint(1000, "g", product(500, "g")) == 2
    assert pack_hint(1, "kg", product(300, "g")) == 4
    assert pack_hint(1, "lít", product(250, "ml")) == 4
    assert pack_hint(10, "g", product(500, "g")) == 1               # tối thiểu 1 gói


def test_pack_hint_none_when_units_do_not_match():
    assert pack_hint(4, "quả", product(500, "g")) is None
    assert pack_hint(500, "g", product(250, "ml")) is None            # khối lượng với thể tích
    assert pack_hint(500, "g", product(None, None)) is None
    assert pack_hint(None, "g", product(500, "g")) is None


def test_two_sections_default_quantities():
    lines = [line("cá lóc", "core", "CAT-1", 500, "g"), line("muối", "addon", "CAT-2", 5, "g"),
             line("rau thơm", "side", "CAT-1"), line("nước dùng", "core", "CAT-1", status="bo_khong_phai_hang_mua")]
    basket = build_basket(lines, CATALOG, recipe_servings=4, servings=4)
    assert [i.ingredient for i in basket.buy] == ["cá lóc"]
    assert [i.ingredient for i in basket.maybe_have] == ["muối"]
    assert basket.buy[0].default_qty == 1 and basket.maybe_have[0].default_qty == 0


def test_scales_need_by_servings_and_gives_pack_hint():
    basket = build_basket([line("cá lóc", "core", "CAT-1", 500, "g")], CATALOG, recipe_servings=2, servings=6)
    item = basket.buy[0]
    assert item.need.quantity == 1500 and item.need.scaled_for == 6
    assert item.pack_hint == 3


def test_have_moves_core_item_to_maybe_have_with_zero():
    lines = [line("cà chua", "core", "CAT-1", 2, "quả"), line("cá lóc", "core", "CAT-2", 500, "g")]
    basket = build_basket(lines, CATALOG, 4, 4, have=["Cà chua"])
    assert [i.ingredient for i in basket.buy] == ["cá lóc"]
    assert basket.maybe_have[0].ingredient == "cà chua" and basket.maybe_have[0].default_qty == 0
    basket = build_basket(lines, CATALOG, 4, 4, have=["CAT-2"])        # theo catalog_id
    assert [i.ingredient for i in basket.buy] == ["cà chua"]


def test_same_ingredient_lines_are_merged_when_unit_matches():
    lines = [line("hành lá", "core", "CAT-1", 20, "g"), line("hành lá", "core", "CAT-1", 10, "g")]
    basket = build_basket(lines, CATALOG, 4, 4)
    assert len(basket.buy) == 1 and basket.buy[0].need.quantity == 30


def test_unknown_catalog_product_is_skipped_and_alternatives_kept():
    lines = [line("a", "core", "CAT-404"), line("b", "core", "CAT-1", alternatives=("CAT-2",))]
    basket = build_basket(lines, CATALOG, 4, 4)
    assert [i.ingredient for i in basket.buy] == ["b"]
    assert basket.buy[0].alternatives[0].catalog_id == "CAT-2"
    assert basket.buy[0].need is None and basket.buy[0].pack_hint is None
