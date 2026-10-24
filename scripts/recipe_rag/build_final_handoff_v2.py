"""Bộ BÀN GIAO v2 cho bên web: catalog mở rộng, nguyên liệu -> catalog_id, và giỏ hàng cho tất cả món phổ biến.

Chạy từ thư mục grocery-store-ai (sau build_catalog_v2.py và build_catalog_ids.py):
    .venv\\Scripts\\python scripts\\recipe_rag\\build_final_handoff_v2.py

Đầu ra (data/recipe_rag/final/, bộ v1 giữ nguyên):
    catalog_v2.json / catalog_v2.csv   catalog đầy đủ, mỗi sản phẩm có catalog_id KHÓA CỨNG (id cũ không đổi)
    ingredient_to_catalog_v2.json      tên nguyên liệu (kể cả tên viết khác) -> danh sách catalog_id (cái đầu = mặc định)
    recipe_ingredients_v2.csv          mỗi dòng nguyên liệu của mỗi món + sản phẩm catalog đã ghép (dễ đọc, lọc trong Excel)
    recipes_matched_v2.json            cùng nội dung với CSV nhưng lồng nhau: món -> nguyên liệu -> sản phẩm đã ghép (JSON thường, không phải JSONL)
    recipes_v2.json                    100 món mục tiêu + các món phổ biến, nguyên liệu gốc và giỏ hàng (catalog_id + số gói)
    validation_report_v2.txt           kết quả kiểm tra tự động

Thứ tự tìm sản phẩm cho một tên nguyên liệu (dừng ở bước đầu tiên có kết quả):
  1. sản phẩm mới đợt 2 (hoặc sản phẩm cũ mà quyết định trùng đã chỉ định) theo tên/alias, hoặc đúng tên sản phẩm trong catalog
  2. bảng ghép đã duyệt của 100 món (ingredient_to_catalog_v1.json)
  3. quyết định đã duyệt: gop / che_bien_tu -> ghép theo nguyên liệu đích; bo -> bỏ khỏi giỏ
  4. gộp tên bạn đã duyệt ở sheet gop_ten_de_xuat -> ghép theo nguyên liệu đích
  5. luật khớp tên của pipeline (find_matches) trên catalog có sẵn
Quy tắc số gói giống v1 (xem build_final_handoff.py): mặc định 1 gói, chỉ g/kg/ml/lít mới tính nhiều gói.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

from build_catalog_clean import clean_product
from build_catalog_ids import key_of, load_registry
from build_final_handoff import packs_needed, parse_steps
from build_recipe_shortlist import PANTRY, find_matches, load_full_catalog
from suggest_catalog_expansion import not_purchasable

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "data" / "recipe_rag" / "review"
FINAL = ROOT / "data" / "recipe_rag" / "final"
CATALOG_V2 = ROOT / "data" / "recipe_rag" / "raw" / "catalogs" / "products_clean_recipes_v2.json"
MAX_CHOICES = 5
OUTPUTS = ["catalog_v2.json", "catalog_v2.csv", "ingredient_to_catalog_v2.json", "recipes_v2.json", "recipe_ingredients_v2.csv", "recipes_matched_v2.json", "validation_report_v2.txt"]
# Tên nguyên liệu mà luật khớp tự động bỏ sót (tên ngắn, tên dài, tên viết khác) -> mảnh tên sản phẩm trong catalog.
# Người rà soát (AI) chọn tay; sản phẩm đầu tiên chứa mảnh tên đó được dùng. Kết quả in ở cuối báo cáo để kiểm.
MANUAL_BY_SUBSTRING = {
    "hẹ": "hẹ lá", "mẻ": "cơm mẻ", "mộc nhĩ": "nấm mèo", "cá cơm than": "nước mắm cá cơm than knorr",
    "nước mắm ngon": "nước mắm nam ngư", "nước mắm chay": "nước mắm nam ngư", "nước ngọt coca": "nước ngọt coca",
    "nước chanh dây": "chanh dây", "nước dão dừa": "nước dừa xiêm", "nước dảo dừa": "nước dừa xiêm", "nước gião dừa": "nước dừa xiêm",
    "gia vị nêm sẵn bột chiên giòn": "bột chiên giòn meizan", "nêm sẵn bột tẩm khô chiên giòn": "bột chiên giòn meizan",
    "bột tẩm khô chiên giòn hương vị bơ tỏi": "bột chiên giòn meizan",
    "bánh xếp kiểu nhật gyoza dùng nồi chiên không dầu": "gyoza", "bánh xếp kiểu nhật gyoza dùng nồi chiên không dầu nhân thịt gà": "gyoza",
    "ớt chao đỏ": "chao đậu nành", "bột bánh rán pha sẵn vị sô-cô-la": "bột bánh rán",
}
SKIP = "__bo__"             # nguyên liệu đã quyết định bỏ khỏi giỏ (cách sơ chế, ghi chú...)


def check_writable():
    locked = []
    for name in OUTPUTS:
        path = FINAL / name
        if path.exists():
            try:
                path.open("ab").close()
            except PermissionError:
                locked.append(name)
    if locked:
        raise SystemExit(f"Chưa ghi gì. Đóng các file đang mở (Excel?) rồi chạy lại: {', '.join(locked)}")


def main():
    FINAL.mkdir(parents=True, exist_ok=True)
    check_writable()
    registry = load_registry()["ids"]
    raw_catalog = json.loads(CATALOG_V2.read_text(encoding="utf-8"))
    full = load_full_catalog()
    decisions = json.loads((REVIEW / "catalog_expansion_ai_decisions_v1.json").read_text(encoding="utf-8"))["decisions"]
    adds = json.loads((REVIEW / "catalog_additions_v2_final.json").read_text(encoding="utf-8"))
    v1_entries = {e["ingredient"]: e for e in json.loads((FINAL / "ingredient_to_catalog_v1.json").read_text(encoding="utf-8"))}
    recipes_clean = {r["id"]: r for r in json.loads((ROOT / "data" / "recipe_rag" / "processed" / "recipes_clean.json").read_text(encoding="utf-8"))}
    expansion = json.loads((REVIEW / "catalog_expansion_recipes_v2.json").read_text(encoding="utf-8"))
    shortlist_ids = [r["id"] for r in json.loads((ROOT / "data" / "recipe_rag" / "processed" / "recipes_shortlist.json").read_text(encoding="utf-8"))]

    wb = load_workbook(REVIEW / "catalog_expansion_review_v1.xlsx", read_only=True, data_only=True)
    rows = list(wb["gop_ten_de_xuat"].iter_rows(values_only=True))
    head = rows[0]
    user_alias = {}
    for r in rows[1:]:
        d = dict(zip(head, r))
        if str(d["quyet_dinh"] or "").strip().lower() == "gop":
            user_alias[d["nguyen_lieu_thieu"]] = d["gop_vao"]

    # ---------- catalog_v2 ----------
    by_name = defaultdict(list)
    for p in raw_catalog:
        by_name[p["name"]].append(registry[key_of(p)]["id"])
    catalog = []
    for p in raw_catalog:
        c = clean_product(p)
        cid = registry[key_of(p)]["id"]
        same = [i for i in by_name[p["name"]] if i != cid]
        manual = not p["product_url"]
        catalog.append({
            "catalog_id": cid, "name": p["name"], "category": p["category"], "unit": p.get("unit"),
            "pack_size": c["pack_size"], "pack_unit": c["pack_unit"], "product_url": p["product_url"],
            "image_url": p.get("image_url"), "source": "manual_added" if manual else "bachhoaxanh",
            "needs_review": manual,
            "note": (("Sản phẩm thêm tay: tên, đơn vị, danh mục là giá trị tạm, cần nhóm xác nhận. " if manual else "")
                     + (f"Trùng tên với {', '.join(same)} (khác product_url/quy cách). " if same else "")).strip() or None,
            "status": "active",
        })
    catalog.sort(key=lambda r: r["catalog_id"])
    (FINAL / "catalog_v2.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    with (FINAL / "catalog_v2.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(catalog[0]))
        w.writeheader()
        w.writerows(catalog)
    placeholder_ids = {c["catalog_id"] for c in catalog if c["needs_review"]}
    pack_of = {c["catalog_id"]: c for c in catalog}
    first_id_of_name = {}
    for c in catalog:
        first_id_of_name.setdefault(c["name"], c["catalog_id"])

    # ---------- tên nguyên liệu -> catalog_id ----------
    forced = {}                                                  # bước 1
    for a in adds["additions"]:
        cid = registry["manual:" + a["ingredient"]]["id"]
        for n in {a["ingredient"], *a["aliases"], *a.get("merged_ingredients", [])}:
            forced[n] = [cid]
    for ing, u in adds["use_existing"].items():
        cid = first_id_of_name[u["product"]]
        for n in {ing, *u["aliases"]}:
            forced[n] = [cid]
    cache, how = {}, {}

    def first_with(fragment):
        return next((c["catalog_id"] for c in catalog if fragment in c["name"].lower()), None)

    def resolve(name, depth=0):
        if name in cache:
            return cache[name]
        cache[name] = []                                         # chặn vòng
        ids, via = [], None
        if depth > 6:
            pass
        elif name in forced:
            ids, via = forced[name], "san_pham_moi"
        elif name in MANUAL_BY_SUBSTRING and first_with(MANUAL_BY_SUBSTRING[name]):
            ids, via = [first_with(MANUAL_BY_SUBSTRING[name])], "chon_tay"
        elif name in first_id_of_name:                           # đích gộp là TÊN sản phẩm cụ thể trong catalog
            ids, via = [first_id_of_name[name]], "ten_san_pham"
        elif name in v1_entries and v1_entries[name]["catalog_ids"]:
            ids, via = v1_entries[name]["catalog_ids"], "bang_ghep_100_mon"
        elif name in decisions and decisions[name]["quyet_dinh"] == "bo":
            ids, via = SKIP, "bo"
        elif name in decisions and decisions[name]["quyet_dinh"] in ("gop", "che_bien_tu"):
            target = decisions[name]["muc_tieu"].replace(" (đề xuất)", "").strip()
            ids, via = resolve(target, depth + 1), "quyet_dinh_" + decisions[name]["quyet_dinh"]
        elif name in user_alias:
            ids, via = resolve(user_alias[name], depth + 1), "gop_ten_da_duyet"
        else:
            m = find_matches(name, full)
            ids = list(dict.fromkeys(registry["url:" + x["product_url"]]["id"] for x in m if x["product_url"]))[:MAX_CHOICES]
            via = "khop_ten" if ids else None
            if not ids and not_purchasable(name):               # không khớp sản phẩm nào và là cách sơ chế/món tự nấu (nước dùng, cơm trắng...)
                ids, via = SKIP, "khong_phai_hang_mua"
        cache[name] = ids
        how[name] = via
        return ids

    # ---------- recipes_v2 ----------
    meta = {e["id"]: e for e in expansion}
    order = list(dict.fromkeys(shortlist_ids + [e["id"] for e in expansion]))
    recipes, unresolved = [], Counter()
    for rid in order:
        src = recipes_clean[rid]
        lines, baskets = [], {}
        for i in src["ingredients"]:
            kind = "side" if i["role"] == "side" else "addon" if i["name"] in PANTRY else "core"
            lines.append({"ingredient": i["name"], "kind": kind, "quantity": i["quantity"], "unit": i["unit"], "raw_text": i["raw_text"]})
            if kind == "side":
                continue
            ids = resolve(i["name"])
            if ids == SKIP:
                continue
            if not ids:
                unresolved[(kind, i["name"])] += 1
            product = pack_of.get(ids[0]) if ids else None
            packs = packs_needed(i, product) if kind == "core" else 1
            b = baskets.setdefault(i["name"], {"ingredient": i["name"], "kind": kind, "catalog_ids": ids,
                                               "default_catalog_id": ids[0] if ids else None, "packs": 1})
            b["packs"] = max(b["packs"], packs)
        basket = sorted(baskets.values(), key=lambda b: (b["kind"] != "core", b["ingredient"]))
        servings = int(src.get("servings") or 0)
        m = meta.get(rid)
        recipes.append({
            "id": rid, "name": src["name"], "source_url": src["url"], "image_url": src.get("image_url"),
            "servings": servings or 4, "servings_defaulted": servings == 0,
            "time_minutes": src.get("time_minutes"), "difficulty": src.get("difficulty"), "description": src.get("description"),
            "family": m["ho_mon"] if m else None, "family_rank": m["hang"] if m else None, "in_target_set": rid in shortlist_ids,
            "prep_steps": parse_steps(src.get("prep_steps")), "cooking_steps": parse_steps(src.get("cooking_steps")),
            "usage_notes": parse_steps(src.get("usage_notes")), "tips": parse_steps(src.get("tips")),
            "ingredients": lines, "basket": basket,
            "complete": all(b["catalog_ids"] for b in basket if b["kind"] == "core"),
            "depends_on_new_products": sorted({b["default_catalog_id"] for b in basket
                                               if b["kind"] == "core" and b["default_catalog_id"] in placeholder_ids}),
        })
    (FINAL / "recipes_v2.json").write_text(json.dumps(recipes, ensure_ascii=False, indent=1), encoding="utf-8")

    # bảng phẳng dễ đọc: mỗi dòng nguyên liệu của mỗi món -> sản phẩm đã ghép (tên sản phẩm, không chỉ id)
    with (FINAL / "recipe_ingredients_v2.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recipe_id", "recipe_name", "family", "ingredient", "kind", "raw_text", "quantity", "unit", "status",
                    "catalog_id", "product_name", "category", "packs", "match_via", "other_catalog_ids"])
        for r in recipes:
            in_basket = {b["ingredient"]: b for b in r["basket"]}
            for line in r["ingredients"]:
                b = in_basket.get(line["ingredient"])
                if line["kind"] == "side":
                    status = "an_kem_khong_vao_gio"
                elif b is None:
                    status = "bo_khong_phai_hang_mua"
                elif not b["catalog_ids"]:
                    status = "chua_ghep_duoc"
                else:
                    status = "da_ghep"
                prod = pack_of.get(b["default_catalog_id"]) if b and b["default_catalog_id"] else None
                w.writerow([r["id"], r["name"], r["family"] or "", line["ingredient"], line["kind"], line["raw_text"], line["quantity"] if line["quantity"] is not None else "",
                            line["unit"] or "", status, b["default_catalog_id"] if prod else "", prod["name"] if prod else "", prod["category"] if prod else "",
                            b["packs"] if prod else "", how.get(line["ingredient"]) or "", " ".join(b["catalog_ids"][1:]) if b else ""])

    # bản JSON lồng nhau: món -> từng dòng nguyên liệu -> sản phẩm đã ghép (kèm sản phẩm thay thế)
    def product_view(cid):
        c = pack_of[cid]
        return {"catalog_id": cid, "product_name": c["name"], "category": c["category"], "unit": c["unit"]}

    matched = []
    for r in recipes:
        in_basket = {b["ingredient"]: b for b in r["basket"]}
        lines = []
        for line in r["ingredients"]:
            b = in_basket.get(line["ingredient"])
            if line["kind"] == "side":
                status, match = "an_kem_khong_vao_gio", None
            elif b is None:
                status, match = "bo_khong_phai_hang_mua", None
            elif not b["catalog_ids"]:
                status, match = "chua_ghep_duoc", None
            else:
                status = "da_ghep"
                match = {**product_view(b["default_catalog_id"]), "packs": b["packs"], "match_via": how.get(line["ingredient"]),
                         "alternatives": [product_view(c) for c in b["catalog_ids"][1:]]}
            lines.append({"ingredient": line["ingredient"], "kind": line["kind"], "raw_text": line["raw_text"],
                          "quantity": line["quantity"], "unit": line["unit"], "status": status, "match": match})
        matched.append({"id": r["id"], "name": r["name"], "family": r["family"], "servings": r["servings"], "complete": r["complete"],
                        "in_target_set": r["in_target_set"], "ingredients": lines})
    (FINAL / "recipes_matched_v2.json").write_text(json.dumps(matched, ensure_ascii=False, indent=2), encoding="utf-8")

    entries = [{"ingredient": n, "catalog_ids": ids, "default_catalog_id": ids[0], "via": how[n]}
               for n, ids in sorted(cache.items()) if ids and ids != SKIP]
    (FINAL / "ingredient_to_catalog_v2.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- kiểm tra tự động ----------
    problems = []
    ids = [c["catalog_id"] for c in catalog]
    if len(set(ids)) != len(ids):
        problems.append("catalog_id trùng")
    if len(catalog) != len(raw_catalog):
        problems.append("thiếu sản phẩm trong catalog_v2")
    for e in entries:
        for cid in e["catalog_ids"]:
            if cid not in pack_of:
                problems.append(f"'{e['ingredient']}' trỏ tới {cid} không có trong catalog")
    old = {c["catalog_id"]: c["name"] for c in json.loads((FINAL / "catalog_v1.json").read_text(encoding="utf-8"))}
    for cid, name in old.items():
        if pack_of.get(cid, {}).get("name") != name:
            problems.append(f"id cũ {cid} đổi tên/biến mất")
    complete = [r for r in recipes if r["complete"]]
    incomplete = [r for r in recipes if not r["complete"]]
    ready_now = sum(1 for r in complete if not r["depends_on_new_products"])
    via_count = Counter(how.values())
    packs_gt1 = sum(1 for r in recipes for b in r["basket"] if b["packs"] > 1)
    info = [
        f"catalog: {len(catalog)} sản phẩm, id {ids[0]}..{ids[-1]}; thêm tay (cần xác nhận): {len(placeholder_ids)}",
        f"công thức: {len(recipes)} (trong đó 100 món mục tiêu: {sum(1 for r in recipes if r['in_target_set'])}) | giỏ đủ nguyên liệu core: {len(complete)} | thiếu: {len(incomplete)}",
        f"dùng được ngay không cần sản phẩm mới: {ready_now}",
        f"tên nguyên liệu đã ghép: {len(entries)} theo cách: {dict(via_count)}",
        f"nguyên liệu core chưa ghép được: {sum(1 for (k, _) in unresolved if k == 'core')} tên | addon chưa ghép: {sum(1 for (k, _) in unresolved if k == 'addon')} tên",
        f"giỏ có packs > 1: {packs_gt1} dòng",
    ]
    report = ["KẾT QUẢ KIỂM TRA TỰ ĐỘNG (v2)", "=" * 28, *info, "", f"LỖI: {len(problems)}", *[f"  - {p}" for p in problems[:50]], "",
              "Nguyên liệu chưa ghép được (loại, tên, số lượt):", *[f"  {k:5} {n} x{c}" for (k, n), c in unresolved.most_common()], "",
              "Công thức chưa đủ core:",
              *[f"  {r['id']} {r['name']}: " + ", ".join(b["ingredient"] for b in r["basket"] if b["kind"] == "core" and not b["catalog_ids"]) for r in incomplete]]
    report += ["", "Ghép chọn tay (tên nguyên liệu -> sản phẩm đầu tiên chứa mảnh tên):",
               *[f"  {n} -> {pack_of[cache[n][0]]['catalog_id']} {pack_of[cache[n][0]]['name']}" for n in MANUAL_BY_SUBSTRING if cache.get(n) and cache[n] != SKIP],
               *[f"  KHÔNG TÌM THẤY: {n} (mảnh '{f}')" for n, f in MANUAL_BY_SUBSTRING.items() if n in cache and cache[n] == SKIP or (n in cache and not cache[n])]]
    (FINAL / "validation_report_v2.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(info))
    print(f"LỖI: {len(problems)}", *problems[:10], sep="\n  ")
    print("core chưa ghép (top):", [(n, c) for (k, n), c in unresolved.most_common(25) if k == "core"])


if __name__ == "__main__":
    main()
