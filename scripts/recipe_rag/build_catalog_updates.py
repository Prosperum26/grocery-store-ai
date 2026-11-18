"""Liệt kê sản phẩm cần thêm vào catalog để đủ nguyên liệu cho tập công thức mục tiêu.

Chạy từ thư mục grocery-store-ai (sau build_recipe_shortlist.py):
    python scripts/recipe_rag/build_catalog_updates.py

Đầu vào : data/recipe_rag/processed/recipes_shortlist.json            100 công thức đã chọn
          data/recipe_rag/raw/catalogs/products_clean_recipes.json      catalog đang dùng (đã lọc)
          data/recipe_rag/raw/catalogs/products_clean.json              catalog đầy đủ
Đầu ra  : data/recipe_rag/raw/catalogs/product_clean_recipes_updates_v1.json

Chỉ gồm nguyên liệu CORE của các công thức đã chọn mà catalog đang dùng KHÔNG có
(khớp đúng/tiền tố trên tên đã chuẩn hóa, cùng luật với build_recipe_shortlist.py).
Mỗi bản ghi giữ đúng schema của products_clean_recipes.json, thêm 3 trường:
    update_status  "from_full_catalog": catalog đầy đủ có bán, chép nguyên bản ghi sang
                   "need_product": chưa có ở đâu, bản ghi trống để nhóm tự bổ sung
    ingredients    các nguyên liệu (đã chuẩn hóa) cần sản phẩm này
    needed_for     id các công thức cần nguyên liệu này
"""
import json
from collections import defaultdict
from pathlib import Path

from build_catalog_clean import clean_product
from build_recipe_shortlist import find_matches  # dùng chung đúng một luật khớp

ROOT = Path(__file__).resolve().parents[2]
CATALOGS = ROOT / "data" / "recipe_rag" / "raw" / "catalogs"
SHORTLIST = ROOT / "data" / "recipe_rag" / "processed" / "recipes_shortlist.json"
OUT = CATALOGS / "product_clean_recipes_updates_v1.json"
MAX_PRODUCTS = 3  # số sản phẩm lấy từ catalog đầy đủ cho mỗi nguyên liệu
FIELDS = ["name", "brand", "category", "price", "unit", "product_url", "image_url",
          "image_urls", "image_paths", "source", "crawled_at", "raw_name"]


def main():
    shortlist = json.loads(SHORTLIST.read_text(encoding="utf-8"))
    current = json.loads((CATALOGS / "products_clean_recipes.json").read_text(encoding="utf-8"))
    full = json.loads((CATALOGS / "products_clean.json").read_text(encoding="utf-8"))
    raw_by_name = {p["name"]: p for p in full}               # để chép nguyên bản ghi gốc
    current_names = {p["name"] for p in current}
    current = [clean_product(p) for p in current]
    # Chỉ xét sản phẩm của catalog đầy đủ mà catalog đang dùng chưa có
    extra = [clean_product(p) for p in full if p["name"] not in current_names]

    def matches(name, products):
        return [raw_by_name.get(m["product"], m) for m in find_matches(name, products)]

    needed_for = defaultdict(list)  # nguyên liệu core -> id công thức
    for r in shortlist:
        for i in r["ingredients"]:
            if i["kind"] == "core" and r["id"] not in needed_for[i["name"]]:
                needed_for[i["name"]].append(r["id"])

    by_product = {}  # 1 sản phẩm có thể phục vụ nhiều nguyên liệu ("nước dừa", "nước dừa xiêm")
    for name, recipe_ids in sorted(needed_for.items(), key=lambda x: (-len(x[1]), x[0])):
        if matches(name, current):
            continue                                   # catalog đang dùng đã có
        found = matches(name, extra)[:MAX_PRODUCTS]
        if found:
            for p in found:
                rec = by_product.setdefault(p["name"], {**{k: p.get(k) for k in FIELDS},
                                                        "update_status": "from_full_catalog",
                                                        "ingredients": [], "needed_for": []})
                rec["ingredients"].append(name)
                rec["needed_for"] += [i for i in recipe_ids if i not in rec["needed_for"]]
        else:
            by_product[f"need:{name}"] = {**{k: None for k in FIELDS}, "name": name, "source": "manual",
                                          "update_status": "need_product", "ingredients": [name],
                                          "needed_for": recipe_ids}
    updates = list(by_product.values())

    OUT.write_text(json.dumps(updates, ensure_ascii=False, indent=2), encoding="utf-8")
    need = [u for u in updates if u["update_status"] == "need_product"]
    found_ings = {n for u in updates if u["update_status"] == "from_full_catalog" for n in u["ingredients"]}
    print(f"nguyên liệu core trong {len(shortlist)} món: {len(needed_for)} | catalog đang dùng thiếu: {len(found_ings) + len(need)}")
    print(f"  có trong catalog đầy đủ: {len(found_ings)} nguyên liệu ({len(updates) - len(need)} sản phẩm)")
    for u in updates:
        if u["update_status"] == "from_full_catalog":
            print(f"    {u['ingredients']} -> {u['name']} [{u['category']}]")
    print(f"  chưa có ở đâu (need_product): {len(need)} -> {[u['name'] for u in need]}")
    print(f"ghi {len(updates)} bản ghi -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
