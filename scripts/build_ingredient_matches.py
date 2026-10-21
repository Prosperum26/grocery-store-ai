"""Đọc quyết định đã duyệt (ingredient_matches_review_v2.xlsx) -> bảng ghép chính thức nguyên liệu -> sản phẩm.

Chạy từ thư mục grocery-store-ai (sau build_review_v2.py):
    .venv\\Scripts\\python scripts\\build_ingredient_matches.py

Đầu vào : data/review/ingredient_matches_review_v2.xlsx   quyết định của người duyệt
          data/review/catalog_additions_v1.json           sản phẩm cần thêm vào catalog
          data/raw/catalogs/products_clean.json           catalog đầy đủ
          data/processed/recipes_shortlist.json           100 công thức mục tiêu
Đầu ra  : data/review/ingredient_catalog_map_v1.json      BẢNG GHÉP CHÍNH THỨC

Mỗi nguyên liệu có `status`:
    matched          ghép được sản phẩm có sẵn trong catalog (products[0] được chọn sẵn, các cái sau là lựa chọn khác)
    added            chưa có trong catalog nhưng nhóm sẽ thêm (sản phẩm lấy từ catalog_additions_v1.json)
    alias            giống hệt nguyên liệu khác (alias_of), sản phẩm sao chép từ đó
    not_in_catalog   không có và không thêm: hiện "chưa có trong catalog", không đoán
`kind` = core (nguyên liệu chính, vào giỏ chọn sẵn) hoặc addon (pantry: hiện cuối danh sách, KHÔNG chọn sẵn).
`reviewed` = false khi dùng gợi ý của AI mà người duyệt chưa xác nhận (chỉ có ở pantry).
Có lỗi cú pháp/tham chiếu thì in hết lỗi và thoát mã 1, không ghi file.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from build_catalog_clean import clean_product
from build_recipe_shortlist import FULL_CATALOG

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"
SRC = REVIEW / "ingredient_matches_review_v2.xlsx"
ADDITIONS = REVIEW / "catalog_additions_v1.json"
SHORTLIST = ROOT / "data" / "processed" / "recipes_shortlist.json"
OUT = REVIEW / "ingredient_catalog_map_v1.json"
DISAMBIGUATION = REVIEW / "catalog_disambiguation_v1.json"
MAX_CANDIDATES = 8


def text(x):
    return "" if x is None else str(x).strip()


def decision_str(v):
    """Ô quyết định -> chuỗi, chịu được số nguyên 3 và số thực 1.2 (Excel đổi '1,2')."""
    return text(v).replace(".", ",") if isinstance(v, float) else text(v)


def product_record(p, source):
    return {"name": p["name"], "product_url": p.get("product_url"), "category": p["category"],
            "pack_size": p["pack_size"], "pack_unit": p["pack_unit"], "price": p.get("price"), "source": source}


def load_additions():
    data = json.loads(ADDITIONS.read_text(encoding="utf-8"))["additions"]
    out = {}
    for a in data:
        raw = {"name": a["name"], "unit": a["unit"], "category": a["category"], "price": None, "product_url": None}
        out[a["ingredient"]] = product_record(clean_product(raw), "manual_added_v1")
    return out


def parse(decision, cands, suggest, errors, where):
    """Quyết định -> ('none'|'alias'|'products', dữ liệu). `cands` là list tên sản phẩm theo ứng viên_1..n."""
    d = decision_str(decision)
    low = d.lower()
    if low == "ok":
        return parse(suggest, cands, "", errors, where) if text(suggest) else _err(errors, where, "'ok' nhưng goi_y trống")
    if low == "none":
        return "none", None
    if low.startswith("alias:"):
        return "alias", d.split(":", 1)[1].strip()
    if low.startswith("sp:"):
        return "products", [("sp", d.split(":", 1)[1].strip())]
    if re.fullmatch(r"\d+(\s*,\s*\d+)*", d):
        picks = [int(x) for x in re.split(r"\s*,\s*", d)]
        out = []
        for k in picks:
            if not 1 <= k <= len(cands) or not cands[k - 1]:
                return _err(errors, where, f"chọn ứng viên {k} nhưng ô đó trống ({len([c for c in cands if c])} ứng viên)")
            out.append(("cand", cands[k - 1]))
        if len(set(picks)) != len(picks):
            return _err(errors, where, f"chọn trùng ứng viên: {d}")
        return "products", out
    return _err(errors, where, f"không hiểu quyết định '{d}' (dùng: số, 1,3, none, alias:X, sp:TÊN, ok)")


def _err(errors, where, msg):
    errors.append(f"{where}: {msg}")
    return "error", None


def main():
    errors, warnings = [], []
    # Mọi hàng của catalog đầy đủ (KHÔNG bỏ trùng): tên trùng thì phải chọn đúng url ở file disambiguation.
    rows_by_name = {}
    for raw in json.loads(FULL_CATALOG.read_text(encoding="utf-8")):
        rows_by_name.setdefault(raw["name"], []).append(clean_product(raw))
    choices = json.loads(DISAMBIGUATION.read_text(encoding="utf-8"))["choices"]
    additions = load_additions()
    wb = load_workbook(SRC, data_only=True)

    records = {}  # (ingredient) -> record

    def read_sheet(sheet, kind, cand_cols, dec_col, hint_col, note_col):
        ws = wb[sheet]
        head = [text(c.value) for c in ws[1]]
        idx = {h: i for i, h in enumerate(head)}
        for r, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            name = text(row[idx["nguyen_lieu"]])
            if not name:
                continue
            where = f"{sheet} hàng {r} '{name}'"
            if name in records:
                errors.append(f"{where}: trùng tên nguyên liệu")
                continue
            cands = [text(row[idx[c]]).split("  |  ")[0].strip() if text(row[idx[c]]) else "" for c in cand_cols]
            raw_dec = decision_str(row[idx[dec_col]])
            suggest = decision_str(row[idx[hint_col]]) if hint_col else ""
            reviewed = bool(raw_dec)
            if not raw_dec:
                if kind == "core":
                    errors.append(f"{where}: chưa có quyet_dinh")
                    continue
                raw_dec = suggest          # pantry: dùng gợi ý AI, đánh dấu chưa duyệt
            note = text(row[idx[note_col]]) if note_col else ""
            action, data = parse(raw_dec, cands, suggest, errors, where)
            records[name] = {"ingredient": name, "kind": kind, "action": action, "data": data,
                             "reviewed": reviewed, "note": note, "where": where, "row_decision": raw_dec}

    cand5 = [f"ung_vien_{k}" for k in range(1, 6)]
    cand8 = [f"ung_vien_{k}" for k in range(1, MAX_CANDIDATES + 1)]
    read_sheet("nguyen_lieu", "core", cand5, "quyet_dinh", "goi_y", "ghi_chu")
    read_sheet("pantry_san_pham", "addon", cand8, "quyet_dinh", "goi_y", "ghi_chu")

    # pantry: sheet `pantry` chỉ xác nhận "list cuối"; 'bo' nghĩa là bỏ khỏi pantry (chưa hỗ trợ -> báo)
    for row in wb["pantry"].iter_rows(min_row=2, values_only=True):
        name, dec = text(row[0]), text(row[5]).lower()
        if dec not in ("list cuối", "giu", "giữ", ""):
            errors.append(f"pantry '{name}': quyết định '{dec}' chưa được hỗ trợ (hiện chỉ 'list cuối'/'giu')")
        if name and name not in records:
            errors.append(f"pantry '{name}': thiếu ở sheet pantry_san_pham")

    # --- Giải quyết thành products / status ---
    def resolve_products(rec):
        out = []
        for kind, value in rec["data"]:
            rows = rows_by_name.get(value)
            if not rows:
                errors.append(f"{rec['where']}: sản phẩm '{value}' không có trong catalog")
                continue
            if len(rows) > 1:                                   # tên trùng -> phải có lựa chọn url rõ ràng
                url = choices.get(value, {}).get("product_url")
                rows = [r for r in rows if r["product_url"] == url]
                if not rows:
                    errors.append(f"{rec['where']}: '{value}' trùng tên nhiều sản phẩm, thêm vào {DISAMBIGUATION.name}")
                    continue
            out.append(product_record(rows[0], "catalog"))
        return out

    resolved = {}
    for name, rec in records.items():
        if rec["action"] == "products":
            resolved[name] = {"status": "matched", "products": resolve_products(rec)}
        elif rec["action"] == "none":
            if name in additions:
                resolved[name] = {"status": "added", "products": [additions[name]]}
            else:
                if "catalog" in rec["note"].lower():
                    errors.append(f"{rec['where']}: ghi chú nói 'thêm vào catalog' nhưng thiếu trong catalog_additions_v1.json")
                resolved[name] = {"status": "not_in_catalog", "products": []}
        elif rec["action"] == "alias":
            pass
    for name, rec in records.items():                           # alias sau khi các nguyên liệu khác đã có kết quả
        if rec["action"] != "alias":
            continue
        chain, cur = [name], rec["data"]
        while cur in records and records[cur]["action"] == "alias":
            if cur in chain:
                errors.append(f"{rec['where']}: alias vòng {' -> '.join(chain + [cur])}")
                break
            chain.append(cur)
            cur = records[cur]["data"]
        if cur == name or cur not in records:
            errors.append(f"{rec['where']}: alias:{rec['data']} " + ("trỏ về chính nó" if cur == name else "không tìm thấy nguyên liệu đó"))
            continue
        target = resolved.get(cur)
        if target is None:
            errors.append(f"{rec['where']}: alias trỏ tới '{cur}' nhưng nguyên liệu đó chưa có kết quả")
            continue
        resolved[name] = {"status": "alias", "alias_of": cur, "products": target["products"]}
    for ing in additions:
        if ing not in records or resolved.get(ing, {}).get("status") != "added":
            warnings.append(f"catalog_additions_v1.json có '{ing}' nhưng quyết định của nguyên liệu này không phải none")

    # --- Đối chiếu với 100 công thức ---
    shortlist = json.loads(SHORTLIST.read_text(encoding="utf-8"))
    for r in shortlist:
        for i in r["ingredients"]:
            if i["kind"] == "core" and i["name"] not in records:
                errors.append(f"công thức '{r['name']}': nguyên liệu core '{i['name']}' chưa có trong file duyệt")
    if errors:
        print(f"{len(errors)} LỖI, không ghi file:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    out = []
    for name, rec in records.items():
        res = resolved[name]
        out.append({"ingredient": name, "kind": rec["kind"], "status": res["status"],
                    **({"alias_of": res["alias_of"]} if "alias_of" in res else {}),
                    "reviewed": rec["reviewed"], "note": rec["note"], "products": res["products"]})
    out.sort(key=lambda x: (x["kind"], x["ingredient"]))
    OUT.write_text(json.dumps({"source": SRC.name, "ingredients": out}, ensure_ascii=False, indent=2), encoding="utf-8")

    by_status = Counter((o["kind"], o["status"]) for o in out)
    print(f"-> {OUT.relative_to(ROOT)}: {len(out)} nguyên liệu")
    for (kind, status), n in sorted(by_status.items()):
        print(f"   {kind:5s} {status:15s} {n}")
    print(f"   pantry chưa được người duyệt xác nhận (dùng gợi ý AI): {sum(1 for o in out if o['kind'] == 'addon' and not o['reviewed'])}")
    for w in warnings:
        print("   CẢNH BÁO:", w)

    # Công thức nào dùng được ngay (mọi nguyên liệu core có sản phẩm, kể cả sản phẩm sẽ thêm)?
    status = {o["ingredient"]: o["status"] for o in out}
    full_now = full_after = 0
    broken = []
    for r in shortlist:
        core = {i["name"] for i in r["ingredients"] if i["kind"] == "core"}
        missing = sorted(n for n in core if status[n] == "not_in_catalog")
        to_add = sorted(n for n in core if status[n] == "added" or (status[n] == "alias" and next(
            o for o in out if o["ingredient"] == n)["products"][0]["source"] == "manual_added_v1"))
        full_after += not missing
        full_now += not missing and not to_add
        if missing:
            broken.append((r["name"], missing))
    print(f"\ncông thức đủ nguyên liệu core: {full_now}/{len(shortlist)} dùng được ngay; "
          f"{full_after}/{len(shortlist)} sau khi thêm sản phẩm vào catalog")
    for name, miss in broken:
        print(f"   thiếu hẳn: {name} -> {miss}")


if __name__ == "__main__":
    main()
