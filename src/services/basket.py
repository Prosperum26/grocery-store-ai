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
    """Dựng giỏ hai phần từ các dòng nguyên liệu đã ghép của một món.

    lines: ingredients của recipe_basket. catalog: catalog_id -> hàng catalog_product.
    Nguyên liệu chính (core) vào buy với số lượng 1; đồ trong tủ bếp (addon) và đồ khách đã có vào maybe_have với 0.
    Dòng side, dòng bị bỏ khỏi giỏ và dòng chưa ghép được không vào giỏ. Cùng nguyên liệu xuất hiện nhiều dòng thì gộp.
    """
    factor = servings / recipe_servings
    have_norm = {strip_accents(h).strip() for h in (have or [])}
    by_ingredient: dict[str, dict] = {}
    for line in lines:
        if line["status"] != "da_ghep" or line["kind"] == "side":
            continue
        entry = by_ingredient.get(line["ingredient"])
        if entry is None:
            by_ingredient[line["ingredient"]] = {"line": line, "quantity": line["quantity"], "unit": line["unit"]}
        elif entry["quantity"] is not None and line["quantity"] is not None and entry["unit"] == line["unit"]:
            entry["quantity"] += line["quantity"]          # cùng đơn vị thì cộng dồn ("hành lá 20g" + "hành lá 10g")
    buy, maybe = [], []
    for ingredient, entry in by_ingredient.items():
        line, match = entry["line"], entry["line"]["match"]
        row = catalog.get(match["catalog_id"])
        if row is None:                                       # sản phẩm không còn trong catalog: bỏ, không đoán
            continue
        product = Product(catalog_id=row["catalog_id"], name=row["name"], category=row["category"],
                          pack_size=float(row["pack_size"]) if row["pack_size"] is not None else None, pack_unit=row["pack_unit"])
        quantity = entry["quantity"]
        need = Need(quantity=round(quantity * factor, 2), unit=entry["unit"], scaled_for=servings) if quantity is not None else None
        owned = strip_accents(ingredient) in have_norm or product.catalog_id.lower() in have_norm
        is_core = line["kind"] == "core" and not owned
        item = Item(ingredient=ingredient, kind=line["kind"], raw_text=line["raw_text"], need=need, product=product,
                    derived=match.get("match_via") == "quyet_dinh_che_bien_tu", default_qty=1 if is_core else 0,
                    pack_hint=pack_hint(need.quantity, need.unit, product) if need else None,
                    alternatives=[Alternative(catalog_id=a["catalog_id"], name=a["product_name"]) for a in match["alternatives"]])
        (buy if is_core else maybe).append(item)
    return Basket(buy=buy, maybe_have=maybe)
