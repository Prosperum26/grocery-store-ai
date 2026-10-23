"""Xử lý sản phẩm thêm mới nghi trùng (sau check_catalog_duplicates.py) -> catalog_additions_v2_final.json.

Chạy từ thư mục grocery-store-ai:
    .venv\Scripts\python scripts\dedup_catalog_additions_v2.py

Kết luận từng trường hợp do người rà soát (AI) đưa ra sau khi đọc báo cáo trùng:
  USE_EXISTING  trùng thật với sản phẩm đã có trong catalog -> KHÔNG thêm, nguyên liệu trỏ về sản phẩm cũ
  KEEP          khác sản phẩm nghi trùng (khác loại/quy cách) -> giữ nguyên là sản phẩm mới
  còn lại       nghi trùng với một sản phẩm MỚI khác (cùng mặt hàng) -> gộp vào sản phẩm xuất hiện trước
Đầu ra: data/review/catalog_additions_v2_final.json
    additions     sản phẩm mới thật sự cần thêm (đã gộp aliases)
    use_existing  {nguyên liệu đích: {"product": tên sản phẩm cũ, "aliases": [...]}}
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"

# tên sản phẩm mới (đúng như trong catalog_additions_v2.json) -> mảnh tên sản phẩm cũ trong catalog
USE_EXISTING = {
    "Hành boa rô bó 100g": "Hành boa rô 100g",
    "Cải bó xôi bó 200g": "Cải bó xôi 300g",
    "Miến đậu xanh gói 200g": "Miến đậu xanh Phú Hương",
    "Bắp hạt lon 340g": "Bắp Mỹ tách hạt khay 250g",
    "Gia vị bò kho gói 25g": "Xốt gia vị bò kho Cholimex",
    "Cải thảo 500g": "Bắp cải thảo",
    "Cải xanh 300g": "Cải bẹ xanh 400g",
    "Gà má đùi khay 500g": "Má đùi gà cắt sẵn",
    "Kim chi cải thảo hũ 500g": "Kim chi cải thảo Việt Hàn",
    "Dầu điều gói 50ml": "Dầu điều chai 250ml",
    "Phô mai bột 100g": "Bột phô mai Ottogi",
    "Rau ngót bó 200g": "Rau ngót khoảng 250gr",
    "Hạt sen tươi 200g": "Hạt sen tươi gói 200g",
    "Soda lon 330ml": "nước soda Schweppes",
    "Sò lông 1kg": "Thịt sò lông khay 250g",
    "Thịt ếch khay 300g": "Thịt ếch làm sạch khay 250g",
    "Tiêu hạt gói 50g": "Tiêu đen hạt 50g",
    "Trứng vịt muối hộp 4 quả": "Trứng vịt muối hộp 4 quả tươi",
    "Tương chua ngọt chai 250g": "Tương ớt chua ngọt Cholimex",
    "Xốt mè rang chai 250ml": "Nước xốt mè rang Kewpie",
    "Đậu Hà Lan khay 200g": "Đậu Hà Lan vỉ 100g",
    "Ớt sừng đỏ 200g": "Ớt sừng đỏ tươi gói 100g",
}
# nghi trùng nhưng thật ra khác mặt hàng: giữ làm sản phẩm mới
KEEP = {"Chanh muối hũ 300g", "Cá đối 500g", "Củ từ 300g", "Gan heo khay 300g", "Gà ta khay 500g", "Gạch cua 100g",
        "Xốt phô mai cay Aji-Xốt chai 260g", "Tôm đông lạnh 500g", "Cà chua hộp lon 400g", "Tôm viên đông lạnh gói 200g"}


def main():
    data = json.loads((REVIEW / "catalog_additions_v2.json").read_text(encoding="utf-8"))
    adds = data["additions"]
    cat = json.loads((ROOT / "data" / "raw" / "catalogs" / "products_clean_recipes_v2.json").read_text(encoding="utf-8"))
    report = json.loads((REVIEW / "catalog_additions_v2_duplicates.json").read_text(encoding="utf-8"))
    flagged_new = {(r["moi"], r["nguyen_lieu"]): [h["ten"] for h in r["trung_voi"] if h["nguon"] == "new_v2"] for r in report}

    use_existing, kept, first_by_name = {}, [], {}
    for a in adds:
        n = a["name"]
        if n in USE_EXISTING:
            frag = USE_EXISTING[n]
            hits = [p["name"] for p in cat if frag.lower() in p["name"].lower()]
            if not hits:
                raise SystemExit(f"không thấy sản phẩm cũ chứa '{frag}' cho '{n}'")
            use_existing[a["ingredient"]] = {"product": hits[0], "new_name_dropped": n, "aliases": a["aliases"]}
            continue
        dup_new = [] if n in KEEP else flagged_new.get((n, a["ingredient"]), [])
        target = next((first_by_name[d] for d in dup_new if d in first_by_name), None)
        if n in first_by_name and not target:
            target = first_by_name[n]                          # trùng tên hệt nhau với sản phẩm mới trước đó
        if target:
            target["aliases"] = sorted(set(target["aliases"]) | set(a["aliases"]) | {a["ingredient"]})
            target.setdefault("merged_ingredients", []).append(a["ingredient"])
            continue
        kept.append(a)
        first_by_name[n] = a
    out = {"additions": kept, "use_existing": use_existing, "maps_to_existing": data["maps_to_existing"], "dropped": data["dropped"]}
    (REVIEW / "catalog_additions_v2_final.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"sản phẩm mới ban đầu {len(adds)} -> giữ {len(kept)} | trùng sản phẩm cũ (không thêm): {len(use_existing)} | gộp vào sản phẩm mới khác: {len(adds) - len(kept) - len(use_existing)}")
    names = [a["name"] for a in kept]
    dup = sorted({n for n in names if names.count(n) > 1})
    print("tên còn trùng:", dup)
    for a in kept:
        if a.get("merged_ingredients"):
            print("  gộp:", a["name"], "<-", a["merged_ingredients"])


if __name__ == "__main__":
    main()
