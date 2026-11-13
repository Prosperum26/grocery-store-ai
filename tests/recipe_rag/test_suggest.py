"""SuggestService: luật xếp hạng trên dữ liệu mẫu nhỏ (không DB, không model)."""
from src.services.suggest_service import SuggestService


def line(cid: str, name: str, kind: str = "core") -> dict:
    return {"ingredient": name, "raw_text": f"{name} 100g", "kind": kind, "status": "da_ghep", "quantity": 100, "unit": "g",
            "match": {"catalog_id": cid, "alternatives": []}}


def recipe(rid: str, cids: list[str], family: str | None = None, in_target: bool = False, complete: bool = True) -> dict:
    return {"id": rid, "name": rid, "source_url": "u", "image_url": None, "description": None, "servings": 4, "time_minutes": 30,
            "difficulty": None, "prep_steps": [], "cooking_steps": [], "usage_notes": [], "tips": [], "family": family,
            "complete": complete, "in_target_set": in_target, "ingredients": [line(c, f"nl-{c}") for c in cids]}


def catalog(*cids: str, review: tuple[str, ...] = ()) -> dict:
    return {c: {"catalog_id": c, "name": f"SP {c}", "category": "x", "unit": "g", "pack_size": 100, "pack_unit": "g",
                "needs_review": c in review} for c in cids}


# Đồ nền: ONION có mặt ở mọi món. FISH chỉ ở canh-ca; PORK ở thit-kho và thit-rang (cùng họ "thit").
RECIPES = {
    "canh-ca": recipe("canh-ca", ["ONION", "FISH", "TOMATO", "DILL"], family="canh", in_target=True),
    "thit-kho": recipe("thit-kho", ["ONION", "PORK", "EGG", "SAUCE"], family="thit"),
    "thit-rang": recipe("thit-rang", ["ONION", "PORK", "PEPPER", "SALT"], family="thit"),
    "rau-xao": recipe("rau-xao", ["ONION", "MORNING", "GARLIC"], family="rau", in_target=True),
    "ngan": recipe("ngan", ["FISH", "TOMATO"], family="ngan"),                                    # chỉ 2 nguyên liệu core
    "tam": recipe("tam", ["ONION", "FISH", "TEMP", "GARLIC"], family="tam"),                       # có sản phẩm needs_review
    "do-dang": recipe("do-dang", ["ONION", "FISH", "TOMATO", "SALT"], family="dd", complete=False),
}
# 20 món đệm với sản phẩm riêng: N đủ lớn để ngưỡng đồ nền 15% có nghĩa (dữ liệu thật có ~1.000 món).
for i in range(20):
    RECIPES[f"dem-{i}"] = recipe(f"dem-{i}", [f"D{i}a", f"D{i}b", f"D{i}c"], family=f"dem-{i}")
FILLER = [f"D{i}{x}" for i in range(20) for x in "abc"]
IDS = FILLER + ["ONION", "FISH", "TOMATO", "DILL", "PORK", "EGG", "SAUCE", "PEPPER", "SALT", "MORNING", "GARLIC", "TEMP"]


def service(skip_needs_review: bool = True, **kw) -> SuggestService:
    return SuggestService(RECIPES, catalog(*IDS, review=("TEMP",)), default_servings=4, skip_needs_review=skip_needs_review, **kw)


def test_needs_review_products_are_allowed_by_default_and_skippable():
    assert "tam" in service(skip_needs_review=False).eligible
    assert "tam" not in service(skip_needs_review=True).eligible


def test_ineligible_recipes_never_appear():
    s = service()
    assert "ngan" not in s.eligible          # quá ngắn
    assert "tam" not in s.eligible           # có sản phẩm needs_review (khi bật skip_needs_review)
    assert "do-dang" not in s.eligible       # chưa complete
    out = s.by_products(["FISH", "TOMATO"], "cart", 12, [], [])
    assert [x.recipe.id for x in out] == ["canh-ca"]


def test_staple_alone_gives_nothing_in_cart_mode():
    s = service()
    assert s.weight["ONION"] == 0
    assert s.by_products(["ONION"], "cart", 9, [], []) == []


def test_single_rare_product_returns_its_only_recipe():
    s = service()
    out = s.by_products(["FISH"], "cart", 9, [], [])
    assert [x.recipe.id for x in out] == ["canh-ca"]
    assert [m.catalog_id for m in out[0].matched] == ["FISH"]
    assert out[0].matched[0].name == "nl-FISH"           # tên nguyên liệu của công thức, không phải tên sản phẩm


def test_one_recipe_per_family():
    s = service()
    out = s.by_products(["PORK"], "cart", 9, [], [])
    assert len(out) == 1 and out[0].recipe.id in {"thit-kho", "thit-rang"}    # hai món cùng họ chỉ lấy một


def test_cart_ranks_by_covered_share():
    s = service()
    # Giỏ đã phủ cả FISH, TOMATO, DILL của canh-ca; PORK chỉ là một phần của món thịt.
    out = s.by_products(["FISH", "TOMATO", "DILL", "PORK"], "cart", 9, [], [])
    assert out[0].recipe.id == "canh-ca"


def test_have_removes_lines_from_the_basket():
    s = service()
    out = s.by_products(["FISH"], "cart", 1, ["CAT-none", "TOMATO"], [])
    names = [i.product.catalog_id for i in out[0].basket.buy]
    assert "TOMATO" not in names and out[0].missing_count == len(out[0].basket.buy)


def test_product_mode_works_for_a_staple():
    s = service()
    out = s.by_products(["ONION"], "product", 9, [], [])
    assert {x.recipe.id for x in out} == {"canh-ca", "thit-kho", "rau-xao"}      # mỗi họ một món, đủ điều kiện
    assert out[0].recipe.id == "rau-xao"                                         # ONION là nguyên liệu core đầu + món gọn nhất


def test_exclude_ids_are_respected():
    s = service()
    out = s.by_products(["ONION"], "product", 9, [], ["rau-xao"])
    assert "rau-xao" not in {x.recipe.id for x in out}


def test_discover_same_seed_same_result_other_seed_may_differ():
    s = service()
    a = s.discover([], [], "cus_1:2026-11-13", 2, [])
    b = s.discover([], [], "cus_1:2026-11-13", 2, [])
    assert [x.recipe.id for x in a] == [x.recipe.id for x in b]
    orders = {tuple(x.recipe.id for x in s.discover([], [], f"seed{i}", 2, [])) for i in range(20)}
    assert len(orders) > 1


def test_discover_without_history_only_returns_target_set():
    s = service()
    out = s.discover([], [], "x", 12, [])
    assert {x.recipe.id for x in out} == {"canh-ca", "rau-xao"}


def test_discover_prefers_two_to_four_new_and_one_to_two_familiar():
    s = service()
    # Khách đã mua ONION và PORK: thit-kho có 2 mới (EGG, SAUCE) + 2 quen, rau-xao có 2 mới + 1 quen, canh-ca có 3 mới + 1 quen.
    out = s.discover(["ONION", "PORK"], [], "x", 12, [])
    ids = {x.recipe.id for x in out}
    assert "rau-xao" in ids and len(ids & {"thit-kho", "thit-rang"}) == 1      # món cùng họ chỉ lấy một
    by_id = {x.recipe.id: x for x in out}
    assert (by_id["rau-xao"].new_count, by_id["rau-xao"].familiar_count) == (2, 1)
    assert not any(i.startswith("dem-") for i in ids)       # món đệm không có nguyên liệu quen nên không vào bậc 1


def test_discover_skips_recipes_the_cart_already_covers_and_honours_exclude():
    s = service()
    out = s.discover(["ONION"], ["ONION", "MORNING", "GARLIC"], "x", 12, ["canh-ca"])
    ids = {x.recipe.id for x in out}
    assert "rau-xao" not in ids and "canh-ca" not in ids
