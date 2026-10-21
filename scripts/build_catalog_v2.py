"""Tạo catalog mới products_clean_recipes_v2.json = catalog đang dùng + sản phẩm đã chọn + sản phẩm thêm mới.

Chạy từ thư mục grocery-store-ai (sau build_ingredient_matches.py):
    .venv\\Scripts\\python scripts\\build_catalog_v2.py

Đầu vào : data/raw/catalogs/products_clean_recipes.json   catalog đang dùng (KHÔNG bị sửa)
          data/raw/catalogs/products_clean.json           catalog đầy đủ
          data/review/ingredient_catalog_map_v1.json      bảng ghép chính thức
          data/review/catalog_additions_v1.json           sản phẩm thêm mới
Đầu ra  : data/raw/catalogs/products_clean_recipes_v2.json

Thứ tự bản ghi: (1) toàn bộ catalog đang dùng, (2) sản phẩm bảng ghép chọn nhưng catalog đang dùng chưa có
(chép nguyên bản ghi từ catalog đầy đủ, thêm `added_from: "full_catalog"`), (3) sản phẩm thêm mới
(`source: "manual_added_v1"`, `price: null`, `placeholder_fields` liệt kê trường cần nhóm điền/sửa).
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "data" / "raw" / "catalogs"
REVIEW = ROOT / "data" / "review"
OUT = CATALOGS / "products_clean_recipes_v2.json"


def main():
    current = json.loads((CATALOGS / "products_clean_recipes.json").read_text(encoding="utf-8"))
    full = {p["name"]: p for p in json.loads((CATALOGS / "products_clean.json").read_text(encoding="utf-8"))}
    mapping = json.loads((REVIEW / "ingredient_catalog_map_v1.json").read_text(encoding="utf-8"))["ingredients"]
    additions = json.loads((REVIEW / "catalog_additions_v1.json").read_text(encoding="utf-8"))["additions"]

    have = {p["name"] for p in current}
    result = list(current)

    picked = []  # sản phẩm có sẵn được chọn nhưng nằm ngoài catalog đang dùng, giữ thứ tự xuất hiện
    for m in mapping:
        for p in m["products"]:
            if p["source"] == "catalog" and p["name"] not in have:
                have.add(p["name"])
                picked.append({**full[p["name"]], "added_from": "full_catalog", "needed_for_ingredient": m["ingredient"]})
    result += picked

    added = []
    for a in additions:
        if a["name"] in have:
            raise SystemExit(f"sản phẩm thêm mới '{a['name']}' trùng tên với sản phẩm đã có")
        added.append({
            "name": a["name"], "brand": None, "category": a["category"], "price": None, "unit": a["unit"],
            "product_url": None, "image_url": None, "image_urls": [], "image_paths": [],
            "source": "manual_added_v1", "crawled_at": None, "raw_name": a["name"],
            "placeholder_fields": ["price", "name", "unit", "category"],
            "needed_for_ingredient": a["ingredient"],
        })
    result += added

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    src = Counter(p.get("added_from") or p["source"] for p in result)
    print(f"-> {OUT.relative_to(ROOT)}: {len(result)} sản phẩm")
    print(f"   catalog đang dùng: {len(current)} | chọn thêm từ catalog đầy đủ: {len(picked)} | thêm mới (chưa có giá): {len(added)}")
    print("   theo nguồn:", dict(src))
    print("   thêm từ catalog đầy đủ:", [p["name"][:42] for p in picked][:6], "...")


if __name__ == "__main__":
    main()
