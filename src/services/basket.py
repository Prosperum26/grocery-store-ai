"""Giỏ hàng hai phần của một món: hàm thuần, không đụng DB hay model, nên test chạy nhanh và không cần torch.

  - build_basket(): nhân khẩu phần, chia phần buy / maybe_have, tính pack_hint.
  - RecipeService (recipe_service.py) gọi hàm này sau khi tìm món.
"""
import math

from src.schemas.recipe_dto import Alternative, Basket, Item, Need, Product
from src.utils.text_cleaner import strip_accents

# Đơn vị khối lượng / thể tích đổi được về đơn vị gốc: (loại, hệ số). Đơn vị khác (quả, củ, muỗng) không quy đổi.
BASE_UNIT = {"g": ("w", 1), "kg": ("w", 1000), "ml": ("v", 1), "lít": ("v", 1000)}


def pack_hint(quantity: float | None, unit: str | None, product: Product) -> int | None:
    """Số gói gợi ý = làm tròn lên (lượng cần / quy cách). Chỉ khi cùng loại đơn vị (g/kg hoặc ml/lít), ngược lại None."""
    if quantity is None or unit not in BASE_UNIT or product.pack_unit not in BASE_UNIT or not product.pack_size:
        return None
    (kind_a, factor_a), (kind_b, factor_b) = BASE_UNIT[unit], BASE_UNIT[product.pack_unit]
    if kind_a != kind_b:
        return None
    return max(1, math.ceil(quantity * factor_a / (float(product.pack_size) * factor_b)))


def build_basket(lines: list[dict], catalog: dict[str, dict], recipe_servings: int, servings: int,
                 have: list[str] | None = None) -> Basket:
    """Dựng giỏ hai phần từ các dòng nguyên liệu đã ghép của một món. Mỗi SẢN PHẨM chỉ có một dòng trong giỏ.

    lines: ingredients của recipe_basket. catalog: catalog_id -> hàng catalog_product.
    Nguyên liệu chính (core) vào buy với số lượng 1; đồ trong tủ bếp (addon) và đồ khách đã có vào maybe_have với 0.
    Dòng side, dòng bị bỏ khỏi giỏ và dòng chưa ghép được không vào giỏ.
    Gộp hai lần: (1) cùng nguyên liệu ở nhiều dòng công thức ("hành lá 20g" + "hành lá 10g");
    (2) nhiều nguyên liệu cùng ghép vào một sản phẩm ("rau om" và "ngò gai" -> gói "Ngò gai, rau om"),
    nếu không khách sẽ thấy một sản phẩm hai lần và mua thừa.
    """
    factor = servings / recipe_servings
    have_norm = {strip_accents(h).strip() for h in (have or [])}

    # (1) Gộp theo nguyên liệu, giữ thứ tự công thức.
    by_ingredient: dict[str, dict] = {}
    for line in lines:
        if line["status"] != "da_ghep" or line["kind"] == "side":
            continue
        entry = by_ingredient.get(line["ingredient"])
        if entry is None:
            by_ingredient[line["ingredient"]] = {"line": line, "quantity": line["quantity"], "unit": line["unit"]}
        elif entry["quantity"] is not None and line["quantity"] is not None and entry["unit"] == line["unit"]:
            entry["quantity"] += line["quantity"]          # cùng đơn vị thì cộng dồn

    # (2) Gộp theo sản phẩm.
    by_product: dict[str, list[tuple[str, dict]]] = {}
    for ingredient, entry in by_ingredient.items():
        catalog_id = entry["line"]["match"]["catalog_id"]
        if catalog_id in catalog:                           # sản phẩm không còn trong catalog: bỏ, không đoán
            by_product.setdefault(catalog_id, []).append((ingredient, entry))

    buy, maybe = [], []
    for catalog_id, entries in by_product.items():
        row = catalog[catalog_id]
        names = [name for name, _ in entries]
        first_line = entries[0][1]["line"]
        product = Product(catalog_id=row["catalog_id"], name=row["name"], category=row["category"],
                          pack_size=float(row["pack_size"]) if row["pack_size"] is not None else None, pack_unit=row["pack_unit"])
        quantity, unit = _total(entries)
        need = Need(quantity=round(quantity * factor, 2), unit=unit, scaled_for=servings) if quantity is not None else None
        # Khách chỉ "đã có" sản phẩm này khi có đủ mọi nguyên liệu nó phục vụ (hoặc nêu thẳng catalog_id).
        owned = product.catalog_id.lower() in have_norm or all(strip_accents(name) in have_norm for name in names)
        kind = "core" if any(e["line"]["kind"] == "core" for _, e in entries) else "addon"
        is_core = kind == "core" and not owned
        raw_texts = list(dict.fromkeys(e["line"]["raw_text"] for _, e in entries))      # bỏ trùng, giữ thứ tự
        item = Item(ingredient=", ".join(names), ingredients=names, kind=kind, raw_text="; ".join(raw_texts), need=need, product=product,
                    derived=all(e["line"]["match"].get("match_via") == "quyet_dinh_che_bien_tu" for _, e in entries),
                    default_qty=1 if is_core else 0,
                    pack_hint=pack_hint(need.quantity, need.unit, product) if need else None,
                    alternatives=[Alternative(catalog_id=a["catalog_id"], name=a["product_name"]) for a in first_line["match"]["alternatives"]])
        (buy if is_core else maybe).append(item)
    return Basket(buy=buy, maybe_have=maybe)


def _total(entries: list[tuple[str, dict]]) -> tuple[float | None, str | None]:
    """Lượng cần của một sản phẩm: cộng được khi mọi nguyên liệu đều ghi lượng cùng đơn vị, ngược lại không ghi lượng."""
    quantities = [e["quantity"] for _, e in entries]
    units = {e["unit"] for _, e in entries}
    if any(q is None for q in quantities) or len(units) != 1:
        return None, None
    return sum(quantities), units.pop()
