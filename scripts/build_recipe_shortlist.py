"""Lọc tập công thức mục tiêu: các món mà mọi nguyên liệu core đều có sản phẩm trong catalog.

Chạy từ thư mục grocery-store-ai:  python scripts/build_recipe_shortlist.py

Đầu vào : data/processed/recipes_clean.json, data/processed/catalog_clean.json,
          data/raw/catalogs/products_clean.json (catalog đầy đủ, chưa lọc)
Đầu ra  : data/processed/recipes_shortlist.json        100 công thức + sản phẩm khớp cho từng nguyên liệu
          data/processed/recipes_shortlist_review.csv  mỗi dòng 1 nguyên liệu, để duyệt tay (cột accept)

Quy tắc (đơn giản, có chủ đích, để duyệt tay chứ chưa phải ghép chính thức):
- core   = nguyên liệu role "main" không nằm trong PANTRY. Chỉ core quyết định món có được chọn.
- khớp   = catalog ĐẦY ĐỦ được chuẩn hóa bằng cùng `clean_product`; nguyên liệu khớp khi `base`
           trùng đúng tên, hoặc BẮT ĐẦU bằng tên đó ("cà chua" khớp "cà chua bi").
           Không dùng "chứa cụm từ ở giữa": cách đó cho "đậu phộng" khớp "Bơ đậu phộng",
           "tôm sú" khớp "Mì 3 Miền tôm sú" (đã thử, sai hàng loạt).
- chọn   = xếp món theo số core còn thiếu (ít trước), rồi nguyên liệu thiếu mở khóa nhiều món
           nhất, rồi món có nhiều core khớp nhất; lấy TARGET món đầu.
"""
import csv
import json
from collections import Counter
from pathlib import Path

from build_catalog_clean import clean_product

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
FULL_CATALOG = ROOT / "data" / "raw" / "catalogs" / "products_clean.json"
TARGET = 100
MAX_MATCHES = 3  # số sản phẩm hiện cho mỗi nguyên liệu khi duyệt

# Đồ nhà thường có sẵn: không bắt buộc catalog phải bán. DANH SÁCH NÀY CHƯA ĐƯỢC NHÓM DUYỆT.
PANTRY = {
    "dầu ăn", "hạt nêm", "đường", "tiêu", "muối", "bột ngọt", "nước tương", "nước mắm",
    "xốt mayonnaise", "tương ớt", "dầu mè", "dầu hào", "giấm gạo", "bột năng", "tương cà",
    "bột canh", "dầu điều", "rượu trắng", "tỏi", "hành tím", "hành lá", "ngò rí",
    "ớt", "sả", "gừng", "bột tẩm khô chiên giòn", "bột chiên giòn", "nêm sẵn lẩu",
}

# Danh mục KHÔNG phải nguyên liệu nấu ăn (đồ ăn vặt, bánh kẹo, đồ uống pha sẵn, món làm sẵn).
# Nếu không chặn: "đậu phộng" khớp "Đậu phộng vị BBQ" (Hạt khô), "mực" khớp "Mực xé tẩm gia vị"
# (Khô chế biến sẵn), "khoai tây" khớp khoai tây chiên đông lạnh, "sườn non" khớp "Sườn non chay".
EXCLUDED_CATEGORIES = {
    "Bánh snack", "Bánh quy", "Bánh que", "Bánh xốp", "Bánh quế", "Bánh Chocopie", "Bánh trung thu",
    "Bánh gạo", "Kem", "Kẹo dẻo, kẹo marshmallow", "Kẹo cứng", "Kẹo Singum", "Socola", "Trái cây sấy",
    "Hạt khô", "Khô chế biến sẵn", "Hàng đông chế biến", "Đồ chay các loại", "Cơm cháy, bánh tráng",
    "Bánh phồng, bánh đa", "Cháo gói, cháo tươi", "Phở, bún ăn liền", "Nước tăng lực, bù khoáng",
    "Nước trà", "Nước yến", "Trà khô, túi lọc", "Cà phê hoà tan", "Cà phê pha phin", "Cà phê lon",
    "Sữa chua uống liền", "Rau câu, thạch dừa", "Bàn chải cho bé", "Dao, kéo", "Thuốc nhuộm tóc",
}
# Thịt không ghi loài thì mặc định là thịt heo: "thịt ba chỉ" không được khớp "Thịt ba chỉ bò Mỹ".
MEAT_HEADS = ("thịt", "sườn", "xương", "nạc", "giò")
OTHER_ANIMALS = {"bò", "gà", "vịt", "dê", "cừu", "cá", "tôm", "mực"}


def allowed(name, product):
    """Sản phẩm có được phép khớp nguyên liệu `name` không."""
    if product["category"] in EXCLUDED_CATEGORIES:
        return False
    words, name_words = set(product["base"].split()), set(name.split())
    if "chay" in words and "chay" not in name_words:          # hàng chay chỉ cho món chay
        return False
    if name.startswith(MEAT_HEADS) and (words & OTHER_ANIMALS) - name_words:
        return False
    if name.startswith(MEAT_HEADS) and product["category"] == "Heo, bò, pate hộp":
        return False                                            # món cần thịt tươi, không dùng thịt hộp
    return True


def find_matches(name, catalog):
    """Trả list sản phẩm khớp, khớp đúng trước, tiền tố sau; trong mỗi nhóm hàng tươi (không có
    `form` phi/xay/rang) đứng trước. Rau lá hay được bán kèm chữ "rau": "húng quế" khớp cả
    "Rau húng quế". Chung cho build_recipe_shortlist.py và build_catalog_updates.py."""
    keys = [name] if name.startswith("rau ") else [name, "rau " + name]
    ok = [p for p in catalog if allowed(name, p)]
    # Hàng tươi (không form) trước; hàng bán thùng/lốc xuống cuối vì khách thường mua lẻ.
    fresh_first = lambda ps: sorted(ps, key=lambda p: (p["multipack"] is not None, p["form"] is not None))
    exact = [("exact", p) for p in fresh_first([p for p in ok if p["base"] in keys])]
    prefix = [("prefix", p) for p in fresh_first([p for p in ok if p["base"] not in keys
                                                  and any(p["base"].startswith(k + " ") for k in keys)])]
    return [
        {"source": src, "product": p["name"], "base": p["base"], "form": p["form"], "multipack": p["multipack"],
         "product_url": p["product_url"], "category": p["category"],
         "pack_size": p["pack_size"], "pack_unit": p["pack_unit"], "price": p["price"]}
        for src, p in exact + prefix
    ]


def load_full_catalog():
    """Catalog đầy đủ, chuẩn hóa bằng cùng luật với bước 2, bỏ trùng tên + quy cách."""
    seen, out = set(), []
    for p in json.loads(FULL_CATALOG.read_text(encoding="utf-8")):
        key = (p["name"], p.get("unit"))
        if key not in seen:
            seen.add(key)
            out.append(clean_product(p))
    return out


def main():
    recipes = json.loads((PROC / "recipes_clean.json").read_text(encoding="utf-8"))
    catalog = load_full_catalog()

    cache = {}  # mỗi tên chỉ tìm 1 lần

    def matches(name):
        if name not in cache:
            cache[name] = find_matches(name, catalog)
        return cache[name]

    scored = []
    for r in recipes:
        core = sorted({i["name"] for i in r["ingredients"] if i["role"] == "main" and i["name"] not in PANTRY})
        if not core:
            continue
        missing = [n for n in core if not matches(n)]
        scored.append((r, core, missing))

    full = [s for s in scored if not s[2]]
    # Nguyên liệu thiếu nào "mở khóa" nhiều món nhất (tính trên các món chỉ thiếu 1)
    unlock = Counter(s[2][0] for s in scored if len(s[2]) == 1)
    scored.sort(key=lambda s: (len(s[2]), -sum(unlock[n] for n in s[2]), -len(s[1])))
    chosen = scored[:TARGET]

    out, rows = [], []
    for r, core, missing in chosen:
        ings = []
        for i in r["ingredients"]:
            kind = "side" if i["role"] == "side" else "pantry" if i["name"] in PANTRY else "core"
            m = matches(i["name"])[:MAX_MATCHES] if kind == "core" else []
            ings.append({**{k: i.get(k) for k in ("name", "form", "quantity", "unit", "raw_text")},
                         "kind": kind, "matches": m})
            rows.append([r["id"], r["name"], i["name"], i.get("form") or "", i.get("quantity") or "",
                         i.get("unit") or "", kind,
                         "THIẾU" if kind == "core" and not m else ("có" if m else ""),
                         " || ".join(f"{x['product']} [{x['source']}]" for x in m), ""])
        servings = int(r["servings"] or 0)
        out.append({
            # 94% công thức ghi 4 người; nguồn ghi 0 thì dùng 4 và đánh dấu để duyệt.
            "id": r["id"], "name": r["name"], "url": r["url"], "servings": servings or 4,
            "servings_defaulted": servings == 0,
            "time_minutes": r["time_minutes"], "difficulty": r["difficulty"],
            "status": "full" if not missing else f"missing_{len(missing)}", "missing": missing,
            "core_count": len(core), "ingredients": ings,
        })

    (PROC / "recipes_shortlist.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with (PROC / "recipes_shortlist_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recipe_id", "recipe_name", "ingredient", "form", "quantity", "unit", "kind",
                    "core_status", "matched_products", "accept"])
        w.writerows(rows)

    # Danh sách pantry để nhóm duyệt: món nào trong 100 món dùng nó, catalog có bán không.
    all_count = Counter(i["name"] for r in recipes for i in r["ingredients"] if i["role"] == "main")
    in_short = Counter(i["name"] for r, _, _ in chosen for i in {x["name"]: x for x in r["ingredients"]}.values())
    with (PROC / "pantry_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ingredient", "lines_all_recipes", "recipes_in_shortlist", "catalog_has_it",
                    "example_products", "keep_as_pantry"])
        for name in sorted(PANTRY, key=lambda n: -all_count[n]):
            m = matches(name)
            w.writerow([name, all_count[name], in_short[name], "có" if m else "không",
                        " || ".join(x["product"] for x in m[:MAX_MATCHES]), ""])

    miss_count = Counter(len(s[2]) for s in scored)
    print(f"catalog đầy đủ sau chuẩn hóa: {len(catalog)} sản phẩm")
    print(f"công thức có core: {len(scored)} | đủ 100%: {len(full)} | thiếu 1: {miss_count[1]} | thiếu 2: {miss_count[2]}")
    print(f"chọn {len(chosen)}: " + ", ".join(f"{k} món thiếu {n}" for n, k in sorted(Counter(len(s[2]) for s in chosen).items())))
    print("nguyên liệu thiếu mở khóa nhiều món nhất:", unlock.most_common(12))


if __name__ == "__main__":
    main()
