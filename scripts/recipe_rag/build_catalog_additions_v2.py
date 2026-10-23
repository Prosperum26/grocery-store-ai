"""Tạo danh sách sản phẩm thêm mới đợt 2 (mở rộng cho tất cả món phổ biến) từ quyết định đã duyệt.

Chạy từ thư mục grocery-store-ai (sau triage_catalog_expansion.py candidates):
    .venv\Scripts\python scripts\recipe_rag\build_catalog_additions_v2.py

Đầu vào : data/recipe_rag/review/catalog_expansion_candidates_v2.json     nguyên liệu thiếu (814 tên)
          data/recipe_rag/review/catalog_expansion_ai_decisions_v1.json   quyết định đã duyệt (them / gop / che_bien_tu / bo)
Đầu ra  : data/recipe_rag/review/catalog_additions_v2.json
Mỗi sản phẩm mới ứng với một nguyên liệu "đích" (kết quả theo chuỗi gộp). `aliases` là các tên nguyên liệu
trong công thức sẽ trỏ về sản phẩm này. gộp vào sản phẩm đã có hoặc `che_bien_tu` không thêm sản phẩm: ghi ở `maps_to_existing` (tên -> nguyên liệu gốc đã có).
"""
import json
from collections import defaultdict
from pathlib import Path

from triage_catalog_expansion import CANDIDATES, DECISIONS, resolve

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "recipe_rag" / "review" / "catalog_additions_v2.json"


def main():
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]
    aliases, prepared, dropped = defaultdict(list), {}, []
    for c in candidates:
        kind, target = resolve(c["name"], decisions)
        if kind == "them":
            aliases[target].append(c["name"])
        elif kind == "co_san":
            if target != c["name"]:
                prepared[c["name"]] = target
        elif kind == "bo":
            dropped.append(c["name"])
        else:
            raise SystemExit(f"'{c['name']}' không giải quyết được ({kind})")
    additions = []
    for target, names in sorted(aliases.items()):
        d = decisions[target]
        additions.append({"ingredient": target, "name": d["ten_de_xuat"], "category": d["danh_muc"], "unit": d["don_vi"],
                          "aliases": sorted(set(names)), "ai_confidence": d["chac_chan"]})
    OUT.write_text(json.dumps({"additions": additions, "maps_to_existing": prepared, "dropped": dropped}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {OUT.relative_to(ROOT)}: {len(additions)} sản phẩm mới | gộp/làm từ nguyên liệu đã có: {len(prepared)} | bỏ: {len(dropped)}")
    names = [a["name"] for a in additions]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        print("CẢNH BÁO tên sản phẩm đề xuất trùng nhau:", dup)


if __name__ == "__main__":
    main()
