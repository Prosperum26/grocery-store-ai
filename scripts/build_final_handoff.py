"""Sinh bộ file BÀN GIAO cho bên web: catalog có id, nguyên liệu -> catalog_id, công thức + giỏ hàng.

Chạy từ thư mục grocery-store-ai (sau build_ingredient_matches.py, build_catalog_v2.py, build_catalog_ids.py):
    .venv\\Scripts\\python scripts\\build_final_handoff.py

Đầu ra (data/final/):
    catalog_v1.json / catalog_v1.csv   catalog hoàn chỉnh, mỗi sản phẩm có catalog_id KHÓA CỨNG
    ingredient_to_catalog_v1.json      nguyên liệu -> danh sách catalog_id (cái đầu = mặc định)
    recipes_v1.json                    100 công thức, nguyên liệu gốc và giỏ hàng (catalog_id + số gói)
    validation_report.txt              kết quả kiểm tra tự động
Giá KHÔNG có trong catalog: bên web tự đặt giá (giá crawl bị lệch thang, không dùng được).

Quy tắc số gói (`packs`) trong giỏ: mặc định 1 gói theo đơn vị catalog (mua dư). Chỉ khi công thức
ghi khối lượng/thể tích (g, kg, ml, lít) và nhiều hơn quy cách của sản phẩm mặc định thì
packs = làm tròn lên (cần / quy cách). Không quy đổi đơn vị nào khác (quả, củ, muỗng...).
"""
import ast
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from build_catalog_clean import clean_product
from build_catalog_ids import key_of, load_registry

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"
FINAL = ROOT / "data" / "final"
CATALOG_V2 = ROOT / "data" / "raw" / "catalogs" / "products_clean_recipes_v2.json"
BASE_UNIT = {"g": ("w", 1), "kg": ("w", 1000), "ml": ("v", 1), "lít": ("v", 1000)}


def parse_steps(value):
    """Các trường bước làm trong dữ liệu crawl là chuỗi dạng "['...', '...']"."""
    try:
        out = ast.literal_eval(value) if isinstance(value, str) else value
        return [s.strip() for s in out if s.strip()] if isinstance(out, list) else []
    except (ValueError, SyntaxError):
        return []


def packs_needed(line, product):
    """Số gói cần cho 1 dòng nguyên liệu (xem quy tắc ở docstring đầu file)."""
    q, unit = line.get("quantity"), line.get("unit")
    if q is None or unit not in BASE_UNIT or not product or product["pack_unit"] not in BASE_UNIT:
        return 1
    (d1, f1), (d2, f2) = BASE_UNIT[unit], BASE_UNIT[product["pack_unit"]]
    if d1 != d2 or not product["pack_size"]:
        return 1
    return max(1, math.ceil(q * f1 / (product["pack_size"] * f2)))


OUTPUTS = ["catalog_v1.json", "catalog_v1.csv", "ingredient_to_catalog_v1.json", "recipes_v1.json", "validation_report.txt"]


def check_writable():
    """Dừng NGAY (trước khi ghi bất cứ gì) nếu có file đích đang bị khóa, thường do đang mở trong Excel.
    Nếu không, bộ file có thể dở dang: file này mới, file kia cũ."""
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
    ingredient_map = json.loads((REVIEW / "ingredient_catalog_map_v1.json").read_text(encoding="utf-8"))["ingredients"]
    additions = json.loads((REVIEW / "catalog_additions_v1.json").read_text(encoding="utf-8"))["additions"]
    shortlist = json.loads((ROOT / "data" / "processed" / "recipes_shortlist.json").read_text(encoding="utf-8"))
    recipes_clean = {r["id"]: r for r in json.loads((ROOT / "data" / "processed" / "recipes_clean.json").read_text(encoding="utf-8"))}
    addition_ingredient = {a["name"]: a["ingredient"] for a in additions}

    # ---------- catalog_v1 ----------
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
    (FINAL / "catalog_v1.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    fields = list(catalog[0])
    with (FINAL / "catalog_v1.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(catalog)
    placeholder_ids = {c["catalog_id"] for c in catalog if c["needs_review"]}
    pack_of = {c["catalog_id"]: c for c in catalog}

    # ---------- ingredient_to_catalog_v1 ----------
    def product_id(prod):
        if prod["product_url"]:
            return registry["url:" + prod["product_url"]]["id"]
        return registry["manual:" + addition_ingredient[prod["name"]]]["id"]

    entries = {}
    for o in ingredient_map:
        ids = [product_id(p) for p in o["products"]]
        entries[o["ingredient"]] = {
            "ingredient": o["ingredient"], "kind": o["kind"], "status": o["status"],
            **({"alias_of": o["alias_of"]} if "alias_of" in o else {}),
            "reviewed": o["reviewed"], "catalog_ids": ids, "default_catalog_id": ids[0] if ids else None,
            "note": o["note"] or None,
        }
    (FINAL / "ingredient_to_catalog_v1.json").write_text(
        json.dumps(sorted(entries.values(), key=lambda e: (e["kind"], e["ingredient"])), ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- recipes_v1 ----------
    recipes = []
    for r in shortlist:
        src = recipes_clean[r["id"]]
        lines, baskets = [], {}
        for i in r["ingredients"]:
            kind = {"core": "core", "pantry": "addon", "side": "side"}[i["kind"]]
            lines.append({"ingredient": i["name"], "kind": kind, "quantity": i["quantity"], "unit": i["unit"], "raw_text": i["raw_text"]})
            if kind == "side":
                continue
            e = entries[i["name"]]
            product = pack_of.get(e["default_catalog_id"])
            packs = packs_needed(i, product) if kind == "core" else 1
            b = baskets.setdefault(i["name"], {"ingredient": i["name"], "kind": kind, "catalog_ids": e["catalog_ids"],
                                               "default_catalog_id": e["default_catalog_id"], "packs": 1})
            b["packs"] = max(b["packs"], packs)
        basket = sorted(baskets.values(), key=lambda b: (b["kind"] != "core", b["ingredient"]))
        recipes.append({
            "id": r["id"], "name": r["name"], "source_url": r["url"], "image_url": src.get("image_url"),
            "servings": r["servings"], "servings_defaulted": r["servings_defaulted"],
            "time_minutes": r["time_minutes"], "difficulty": r["difficulty"], "description": src.get("description"),
            "prep_steps": parse_steps(src.get("prep_steps")), "cooking_steps": parse_steps(src.get("cooking_steps")),
            "usage_notes": parse_steps(src.get("usage_notes")), "tips": parse_steps(src.get("tips")),
            "ingredients": lines, "basket": basket,
            "depends_on_new_products": sorted({cid for b in basket if b["kind"] == "core" for cid in [b["default_catalog_id"]]
                                               if cid in placeholder_ids}),
        })
    (FINAL / "recipes_v1.json").write_text(json.dumps(recipes, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- kiểm tra tự động ----------
    problems, info = [], []
    ids = [c["catalog_id"] for c in catalog]
    if len(set(ids)) != len(ids):
        problems.append("catalog_id trùng")
    if len(catalog) != len(raw_catalog):
        problems.append("thiếu sản phẩm trong catalog_v1")
    for e in entries.values():
        for cid in e["catalog_ids"]:
            if cid not in pack_of:
                problems.append(f"'{e['ingredient']}' trỏ tới {cid} không có trong catalog")
        if e["status"] != "not_in_catalog" and not e["catalog_ids"]:
            problems.append(f"'{e['ingredient']}' không có catalog_id")
        if len(set(e["catalog_ids"])) != len(e["catalog_ids"]):
            problems.append(f"'{e['ingredient']}' có catalog_id lặp")
    for r in recipes:
        for b in r["basket"]:
            if b["kind"] == "core" and not b["catalog_ids"]:
                problems.append(f"công thức '{r['name']}': nguyên liệu core '{b['ingredient']}' không có sản phẩm")
    complete = sum(1 for r in recipes if all(b["catalog_ids"] for b in r["basket"] if b["kind"] == "core"))
    ready_now = sum(1 for r in recipes if not r["depends_on_new_products"] and all(b["catalog_ids"] for b in r["basket"] if b["kind"] == "core"))
    packs_gt1 = [(r["name"], b["ingredient"], b["packs"]) for r in recipes for b in r["basket"] if b["packs"] > 1]
    unreviewed = sum(1 for e in entries.values() if not e["reviewed"])
    info += [
        f"catalog: {len(catalog)} sản phẩm, id {ids[0]}..{ids[-1]}; thêm tay (cần xác nhận): {len(placeholder_ids)}",
        f"công thức: {len(recipes)} | đủ nguyên liệu core (kể cả sản phẩm sẽ thêm): {complete} | dùng được ngay không cần sản phẩm mới: {ready_now}",
        f"giỏ hàng có packs > 1: {len(packs_gt1)} dòng", f"nguyên liệu chưa được người duyệt xác nhận (pantry, gợi ý AI): {unreviewed}",
        f"catalog_id mặc định thuộc nhóm sản phẩm thêm tay: {len(set(b['default_catalog_id'] for r in recipes for b in r['basket'] if b['default_catalog_id'] in placeholder_ids))} sản phẩm",
    ]
    report = ["KẾT QUẢ KIỂM TRA TỰ ĐỘNG", "=" * 24, *info, "", f"LỖI: {len(problems)}", *[f"  - {p}" for p in problems],
              "", "Giỏ hàng cần nhiều hơn 1 gói:", *[f"  {a} | {b} x{c}" for a, b, c in packs_gt1]]
    (FINAL / "validation_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(info))
    print(f"LỖI: {len(problems)}", *problems[:10], sep="\n  ")
    print("packs > 1:", packs_gt1)


if __name__ == "__main__":
    main()
