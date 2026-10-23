"""Dò sản phẩm thêm mới (catalog_additions_v2.json) có trùng với catalog hiện tại hoặc trùng nhau không.

Chạy từ thư mục grocery-store-ai:
    .venv\Scripts\python scripts\check_catalog_duplicates.py

So sánh trên "tên lõi" (bỏ quy cách như 500g, 2 lít, hộp 10 quả). Ba kiểu nghi trùng:
  A. tên lõi giống hệt hoặc rất giống (difflib >= 0.88)
  B. mọi từ của tên lõi mới đều có trong tên sản phẩm cũ, và sản phẩm cũ không dài hơn tên mới quá 2 từ
     (ví dụ 'Giá đỗ' và 'Giá đỗ khay 200g')
  C. find_matches (luật khớp của pipeline) trả về sản phẩm cũ cho nguyên liệu đích
Ghi data/review/catalog_additions_v2_duplicates.json để xử lý; không sửa gì khác.
"""
import difflib
import json
import re
import sys
from pathlib import Path

from build_recipe_shortlist import find_matches, load_full_catalog

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"
OUT = REVIEW / "catalog_additions_v2_duplicates.json"
QTY = re.compile(r"\b(khay|gói|goi|hũ|chai|lon|hộp|túi|bó|con|lọ|tuýp|cây|lố|vỉ|bịch)?\s*\d+([.,]\d+)?\s*(g|gr|kg|ml|l|lít|quả|trái|lá|bông|cái|con|gói|viên|lát|miếng)?\b", re.I)


def core(name):
    s = name.lower()
    s = QTY.sub(" ", s)
    s = re.sub(r"\b(khay|gói|hũ|chai|lon|hộp|túi|bó|lọ|tuýp|bịch|nguyên con)\b", " ", s)
    return re.sub(r"[^\w\s]", " ", s).split()


def main():
    additions = json.loads((REVIEW / "catalog_additions_v2.json").read_text(encoding="utf-8"))["additions"]
    old_add = json.loads((REVIEW / "catalog_additions_v1.json").read_text(encoding="utf-8"))["additions"]
    cat = json.loads((ROOT / "data" / "raw" / "catalogs" / "products_clean_recipes_v2.json").read_text(encoding="utf-8"))
    existing = [{"name": p["name"], "category": p["category"], "src": "catalog"} for p in cat]
    existing += [{"name": a["name"], "category": a["category"], "src": "added_v1"} for a in old_add if a["name"] not in {e["name"] for e in existing}]
    full = load_full_catalog()
    ex_core = [(e, core(e["name"])) for e in existing]
    report = []
    for i, a in enumerate(additions):
        c = core(a["name"])
        hits = []
        for e, ec in ex_core:
            ratio = difflib.SequenceMatcher(None, " ".join(c), " ".join(ec)).ratio()
            if ratio >= 0.88:
                hits.append((e, "A", round(ratio, 2)))
            elif c and set(c) <= set(ec) and len(ec) - len(c) <= 2:
                hits.append((e, "B", round(ratio, 2)))
        via_rule = [m["product"] for m in find_matches(a["ingredient"], full)][:3]
        for other in additions[:i]:                      # trùng với sản phẩm mới khác
            oc = core(other["name"])
            if difflib.SequenceMatcher(None, " ".join(c), " ".join(oc)).ratio() >= 0.88 or (c and set(c) <= set(oc) and len(oc) - len(c) <= 1):
                hits.append(({"name": other["name"], "category": other["category"], "src": "new_v2"}, "A/B", 1.0))
        if hits or via_rule:
            report.append({"moi": a["name"], "nguyen_lieu": a["ingredient"], "danh_muc": a["category"],
                           "trung_voi": [{"ten": h[0]["name"], "danh_muc": h[0]["category"], "nguon": h[0]["src"], "kieu": h[1], "do_giong": h[2]} for h in hits[:4]],
                           "find_matches": via_rule})
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(additions)} sản phẩm mới | nghi trùng: {len(report)} -> {OUT.relative_to(ROOT)}")
    for r in report:
        t = "; ".join(f"{h['ten'][:38]} [{h['nguon']},{h['kieu']}]" for h in r["trung_voi"]) or "-"
        print(f"  {r['moi'][:34]:34} | {t} | rule: {[x[:30] for x in r['find_matches']]}")


if __name__ == "__main__":
    main()
