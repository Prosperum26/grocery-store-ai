"""Tạo catalog mới products_clean_recipes_v2.json = catalog đang dùng + sản phẩm đã chọn + sản phẩm thêm mới.

Chạy từ thư mục grocery-store-ai (sau build_ingredient_matches.py):
    .venv\\Scripts\\python scripts\\recipe_rag\\build_catalog_v2.py

Đầu vào : data/recipe_rag/raw/catalogs/products_clean_recipes.json   catalog đang dùng (KHÔNG bị sửa)
          data/recipe_rag/raw/catalogs/products_clean.json           catalog đầy đủ
          data/recipe_rag/review/ingredient_catalog_map_v1.json      bảng ghép chính thức
          data/recipe_rag/review/catalog_additions_v1.json           sản phẩm thêm mới
Đầu ra  : data/recipe_rag/raw/catalogs/products_clean_recipes_v2.json

Thứ tự bản ghi: (1) toàn bộ catalog đang dùng, (2) sản phẩm bảng ghép chọn nhưng catalog đang dùng chưa có
(chép nguyên bản ghi từ catalog đầy đủ, thêm `added_from: "full_catalog"`), (3) sản phẩm thêm mới
(`source: "manual_added_v1"`, `price: null`, `placeholder_fields` liệt kê trường cần nhóm điền/sửa),
(4) phần còn lại của catalog đầy đủ (`added_from: "full_catalog_rest"`): vì catalog này là file để web hiển thị
nên không được bỏ sản phẩm nào là thực phẩm. Chỉ loại các danh mục không phải đồ ăn (NON_FOOD_CATEGORIES),
danh sách loại ghi ở data/recipe_rag/review/catalog_excluded_v1.json.
Thứ tự (4) đứng CUỐI để sản phẩm mới nhận id nối tiếp, không đụng id đã khóa.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOGS = ROOT / "data" / "recipe_rag" / "raw" / "catalogs"
REVIEW = ROOT / "data" / "recipe_rag" / "review"
OUT = CATALOGS / "products_clean_recipes_v2.json"
EXCLUDED = REVIEW / "catalog_excluded_v1.json"
# Danh mục không phải đồ ăn: dao thớt, bàn chải đánh răng, dầu gội nhuộm tóc.
NON_FOOD_CATEGORIES = {"Bàn chải cho bé", "Dao, kéo", "Thuốc nhuộm tóc"}


def main():
    current = json.loads((CATALOGS / "products_clean_recipes.json").read_text(encoding="utf-8"))
    full = {p["product_url"]: p for p in json.loads((CATALOGS / "products_clean.json").read_text(encoding="utf-8"))}
    mapping = json.loads((REVIEW / "ingredient_catalog_map_v1.json").read_text(encoding="utf-8"))["ingredients"]
    additions = json.loads((REVIEW / "catalog_additions_v1.json").read_text(encoding="utf-8"))["additions"]

    have = {p["product_url"] for p in current}
    result = list(current)

    picked = []  # sản phẩm có sẵn được chọn nhưng nằm ngoài catalog đang dùng, giữ thứ tự xuất hiện
    for m in mapping:
        for p in m["products"]:
            if p["source"] == "catalog" and p["product_url"] not in have:
                have.add(p["product_url"])
                picked.append({**full[p["product_url"]], "added_from": "full_catalog", "needed_for_ingredient": m["ingredient"]})
    result += picked

    added = []
    for a in additions:
        if a["name"] in {p["name"] for p in result}:
            raise SystemExit(f"sản phẩm thêm mới '{a['name']}' trùng tên với sản phẩm đã có")
        added.append({
            "name": a["name"], "brand": None, "category": a["category"], "price": None, "unit": a["unit"],
            "product_url": None, "image_url": None, "image_urls": [], "image_paths": [],
            "source": "manual_added_v1", "crawled_at": None, "raw_name": a["name"],
            "placeholder_fields": ["price", "name", "unit", "category"],
            "needed_for_ingredient": a["ingredient"],
        })
    result += added

    rest = [{**p, "added_from": "full_catalog_rest"} for url, p in full.items()
            if url not in have and p["category"] not in NON_FOOD_CATEGORIES]
    excluded = [{"name": p["name"], "category": p["category"], "product_url": p["product_url"],
                 "reason": "không phải đồ ăn (danh mục không thuộc thực phẩm)"}
                for url, p in full.items() if url not in have and p["category"] in NON_FOOD_CATEGORIES]
    result += rest

    # (5) đợt 2: sản phẩm mở rộng cho tất cả món phổ biến (đã duyệt + đã dò trùng). Đứng SAU phần (4) để nhận id nối tiếp.
    additions_v2 = json.loads((REVIEW / "catalog_additions_v2_final.json").read_text(encoding="utf-8"))["additions"]
    taken = {p["name"] for p in result}
    added_v2 = []
    for a in additions_v2:
        if a["name"] in taken:
            raise SystemExit(f"sản phẩm thêm mới đợt 2 '{a['name']}' trùng tên với sản phẩm đã có")
        taken.add(a["name"])
        added_v2.append({
            "name": a["name"], "brand": None, "category": a["category"], "price": None, "unit": a["unit"],
            "product_url": None, "image_url": None, "image_urls": [], "image_paths": [],
            "source": "manual_added_v2", "crawled_at": None, "raw_name": a["name"],
            "placeholder_fields": ["price", "name", "unit", "category", "image"],
            "needed_for_ingredient": a["ingredient"],
        })
    result += added_v2
    EXCLUDED.write_text(json.dumps(excluded, ensure_ascii=False, indent=1), encoding="utf-8")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    src = Counter(p.get("added_from") or p["source"] for p in result)
    print(f"-> {OUT.relative_to(ROOT)}: {len(result)} sản phẩm")
    print(f"   catalog đang dùng: {len(current)} | chọn thêm từ catalog đầy đủ: {len(picked)} | thêm mới (chưa có giá): {len(added)}"
          f" | phần còn lại của catalog đầy đủ: {len(rest)} | loại (không phải đồ ăn): {len(excluded)} | thêm mới đợt 2: {len(added_v2)}")
    assert len(current) + len(picked) + len(rest) + len(excluded) == len(full) + (len(current) - len({p["product_url"] for p in current}))
    print("   theo nguồn:", dict(src))
    print("   thêm từ catalog đầy đủ:", [p["name"][:42] for p in picked][:6], "...")


if __name__ == "__main__":
    main()
