"""Chuẩn hóa catalog: data/raw/catalogs/products_clean_recipes.json -> data/processed/catalog_clean.json.

Chạy từ thư mục grocery-store-ai:  python scripts/build_catalog_clean.py

Dùng chung hàm `canonical` với build_recipes_clean.py để tên sản phẩm và tên nguyên liệu
đi qua cùng một bộ luật, nhờ đó mới ghép được với nhau. Mỗi sản phẩm được tách thành:
    base       loại hàng đã chuẩn hóa ("cà rốt", "nước mắm", "hạt nêm nấm hương")
    form       phi/xay/rang nếu có (giống phía công thức)
    brand      hãng, đoán theo chữ viết hoa (best-effort, trường brand gốc luôn rỗng)
    pack_size, pack_unit, container, multipack   quy cách đóng gói
File raw không bị sửa.
"""
import json
import re
from collections import Counter
from pathlib import Path

from build_recipes_clean import canonical, nfc, parse_number, tidy

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "catalogs" / "products_clean_recipes.json"
OUT = ROOT / "data" / "processed" / "catalog_clean.json"

CONTAINERS = "gói|chai|hộp|bịch|lon|túi|khay|vỉ|hũ|thùng|lốc|bình|can|chén|ly|tô"
# Quy cách: "gói 200g", "chai 1 lít", "500ml", "400gr". Container có thể vắng.
PACK_RE = re.compile(rf"(?:({CONTAINERS})\s+)?(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ml|lít|l)\b", re.IGNORECASE)
# Nhiều đơn vị gộp bán: "18 chai nước chấm ...", "Thùng 12 chai Dầu ăn ..." -> multipack = 18 / 12
MULTIPACK_RE = re.compile(rf"^(?:(?:thùng|lốc)\s+)?(\d+)\s+({CONTAINERS})\s+", re.IGNORECASE)
UNIT_ALIASES = {"l": "lít", "gr": "g"}


def parse_pack(product):
    """(container, pack_size, pack_unit) từ trường unit, thiếu thì tìm ở đuôi tên."""
    for text in (product.get("unit"), product["name"]):
        m = PACK_RE.search(nfc(text or ""))
        if m:
            unit = m.group(3).lower()
            container = m.group(1).lower() if m.group(1) else None
            return container, parse_number(m.group(2)), UNIT_ALIASES.get(unit, unit)
    return None, None, None


def split_brand(name):
    """Hãng = cụm CUỐI gồm các từ viết hoa liền nhau, không tính từ đầu tiên.
    'Hạt nêm nấm hương Knorr gói 800g' -> ('Hạt nêm nấm hương gói 800g', 'Knorr')."""
    words = name.split()
    runs, cur = [], []
    for i, w in enumerate(words):
        if i > 0 and w[:1].isupper() and not w.endswith("%"):
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return name, None
    run = runs[-1]
    brand = " ".join(words[i] for i in run)
    rest = " ".join(w for i, w in enumerate(words) if i not in run)
    return rest, brand


def clean_product(p):
    name = tidy(nfc(p["name"]))
    multipack = None
    m = MULTIPACK_RE.match(name)
    if m:
        multipack, name = int(m.group(1)), name[m.end():]
    container, pack_size, pack_unit = parse_pack(p)
    name = re.sub(r"\([^)]*\)", " ", name)         # "(4 trái)": ghi chú trong ngoặc
    name = PACK_RE.sub(" ", name)                  # bỏ quy cách khỏi tên
    name = re.sub(rf"\b({CONTAINERS})\b\s*$", "", tidy(name), flags=re.IGNORECASE)
    name = re.sub(r"\d+\s*%", " ", name)           # "100%", "12%"
    name, brand = split_brand(tidy(name))
    # Chỉ lấy kết quả đầu: sản phẩm là 1 mặt hàng, không phải danh sách.
    cano = canonical(name)
    base, form = cano[0] if cano else (tidy(name.lower()), None)
    return {
        "name": p["name"], "base": base, "form": form, "brand": brand,
        "category": p["category"], "pack_size": pack_size, "pack_unit": pack_unit,
        "container": container, "multipack": multipack, "price": p["price"],
        "product_url": p["product_url"],
    }


def main():
    products = json.loads(SRC.read_text(encoding="utf-8"))
    seen, cleaned = set(), []
    for p in products:
        key = (p["name"], p.get("unit"))
        if key in seen:                              # 13 sản phẩm trùng tên + quy cách
            continue
        seen.add(key)
        cleaned.append(clean_product(p))
    for i, c in enumerate(cleaned):
        c["id"] = i

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"products: {len(products)} -> {len(cleaned)} (bỏ {len(products) - len(cleaned)} trùng)")
    print(f"có pack_size: {sum(c['pack_size'] is not None for c in cleaned)} | có brand: "
          f"{sum(c['brand'] is not None for c in cleaned)} | multipack: {sum(c['multipack'] is not None for c in cleaned)}")
    print("distinct base:", len({c['base'] for c in cleaned}))
    print("top base:", Counter(c["base"] for c in cleaned).most_common(15))


if __name__ == "__main__":
    main()
