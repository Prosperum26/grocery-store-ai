"""Chuẩn hóa tên nguyên liệu: data/raw/recipes/recipes.json -> data/processed/recipes_clean.json.

Chạy từ thư mục grocery-store-ai:  python scripts/build_recipes_clean.py

Mỗi dòng nguyên liệu thô (raw_text) được tách thành 1 hoặc nhiều nguyên liệu dạng:
    {raw_text, name, quantity, unit, role}
trong đó `name` là tên gốc (canonical) để sau này ghép với catalog.
File raw không bị sửa. Các trường khác của công thức được giữ nguyên.
Dedupe món, lọc theo catalog, cờ pantry/optional là việc của các bước sau.
"""
import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "recipes" / "recipes.json"
OUT = ROOT / "data" / "processed" / "recipes_clean.json"
VOCAB = ROOT / "data" / "processed" / "ingredient_vocab.csv"

# --- Bảng luật (chỉnh ở đây khi xem báo cáo thấy còn tên bẩn) -------------------

# Tiền tố đầu dòng. Nhóm "side" là đồ ăn kèm/trang trí, không phải nguyên liệu chính.
SIDE_PREFIXES = ["rau ăn kèm", "ăn kèm", "rau nêm", "dùng kèm", "trang trí", "nước chấm", "tráng miệng"]
NEUTRAL_PREFIXES = ["bữa sáng", "bữa trưa", "bữa tối"]
PREFIX_RE = re.compile(
    r"^\s*(" + "|".join(SIDE_PREFIXES + NEUTRAL_PREFIXES) + r")\s*:?\s*", re.IGNORECASE
)

# Tên thương hiệu: cắt từ thương hiệu đến hết (bỏ vị/biến thể), giữ loại hàng đứng trước.
#   "hạt nêm aji-ngon heo" -> "hạt nêm";  "nước tương phú sĩ giảm muối" -> "nước tương"
BRAND_CUT_RE = re.compile(r"\s*\b(aji-?ngon|aji-?no-?moto|aji-?mayo|phú sĩ|lisa)\b.*$")
# Thương hiệu đứng đầu/giữa tên: chỉ bỏ chữ thương hiệu, giữ phần còn lại.
#   "aji-quick bột chiên giòn" -> "bột chiên giòn"
BRAND_DROP_RE = re.compile(r"\b(aji-?quick|ajinomoto|blendy)\b")

# Từ chỉ cách sơ chế: cắt từ từ này đến hết tên.  "hành lá cắt nhỏ" -> "hành lá"
# Không cắt các từ đổi bản chất hàng (xay, phi, rang, khô, tươi, chua) vì catalog có bán dạng đó.
PREP_RE = re.compile(
    r"\s+(băm|bằm|cắt|thái|xắt|bào|giã|đập|vắt|rửa|gọt|lột|chặt|bóp|tách|xé|luộc|"
    r"ngâm (mềm|nước|cho)|sơ chế|làm sạch)\b.*$"
)
SIZE_TAIL_RE = re.compile(r"\s+(nhỏ|lớn|to|vừa|ít|đã|loại \w+)$")
# Số lượng đứng đầu tên: "1 con cá điêu hồng" -> "cá điêu hồng"
LEAD_QTY_RE = re.compile(r"^[\d/.,]+\s*(con|quả|trái|củ|cây|miếng|gói)?\s+")

# Đồng nghĩa/viết sai -> tên gốc. Giá trị là list nếu một tên gồm nhiều nguyên liệu.
ALIASES = {
    "hành boa rô": "hành boa rô", "hành boaro": "hành boa rô", "boa rô": "hành boa rô",
    "boa-rô": "hành boa rô", "hành boa-rô": "hành boa rô", "boaro": "hành boa rô",
    "hành tỏi": ["hành tím", "tỏi"],
    "ngò": "ngò rí", "ngò gai": "ngò gai",
    "bột ngọt": "bột ngọt", "mì chính": "bột ngọt",
    "tương cà": "tương cà", "sốt cà": "tương cà",
    "giấm gạo lên men": "giấm gạo",
}

# Đơn vị: gộp cách viết. M/m là viết tắt muỗng canh/muỗng cà phê trong công thức VN.
UNIT_ALIASES = {"l": "lít", "gr": "g", "trái": "quả"}
QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?(?:/\d+)?)\s*([Mm])\b")
METRIC_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|lít|l)\b", re.IGNORECASE)


def nfc(s):
    return unicodedata.normalize("NFC", s)


def parse_number(s):
    """'200' -> 200.0, '1/2' -> 0.5, '1,5' -> 1.5, không đọc được -> None."""
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    try:
        if "/" in s:
            a, b = s.split("/")
            return float(a) / float(b)
        return float(s)
    except ValueError:
        return None


def strip_noise(text):
    """Bỏ ký hiệu ®™*, dấu ngoặc kép, tab/khoảng trắng thừa."""
    text = nfc(text)
    text = re.sub(r"[®™*“”\"]", "", text)
    return re.sub(r"[ \t ]+", lambda m: "\t" if "\t" in m.group() else " ", text).strip()


def split_prefix(text):
    """Tách tiền tố 'ĂN KÈM:' ra khỏi dòng. Trả (role, phần còn lại)."""
    role = "main"
    while True:
        m = PREFIX_RE.match(text)
        if not m:
            return role, text
        if m.group(1).lower() in SIDE_PREFIXES:
            role = "side"
        text = text[m.end():]


def split_head_tail(text):
    """'Cà rốt: 25g' / 'Cà rốt\\t25g' -> ('Cà rốt', '25g'). Phần đầu là tên, phần sau là số lượng/ghi chú."""
    text = re.sub(r"\([^)]*\)", " ", text)       # bỏ nội dung trong ngoặc
    text = re.sub(r"\(.*$", " ", text)            # ngoặc không đóng
    for sep in ("\t", ":"):
        if sep in text:
            head, tail = text.split(sep, 1)
            return head.strip(), tail.strip()
    # Không có dấu phân cách: cắt tại chỗ bắt đầu số lượng ("Hành tây 1/2 củ", "Tỏi băm 2M")
    m = re.search(r"\s\d", text)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    return text.strip(), ""


def canonical(name):
    """Một cụm tên -> tên gốc (list vì 'hành tỏi' tách thành 2). Rỗng nếu không còn gì."""
    name = name.lower().strip(" .;-–&")
    name = LEAD_QTY_RE.sub("", name)
    name = re.sub(r"\s+\d.*$", "", name)          # đuôi số lượng còn sót
    name = BRAND_CUT_RE.sub("", name)
    name = BRAND_DROP_RE.sub("", name)
    name = PREP_RE.sub("", name)
    name = SIZE_TAIL_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .;-–&")
    alias = ALIASES.get(name, name)
    out = alias if isinstance(alias, list) else [alias]
    return [n for n in out if len(n) >= 2]


def parse_quantity(ing, tail):
    """Lấy (quantity, unit): ưu tiên amount/unit crawler đã tách, thiếu thì đọc 1M/2m trong dòng."""
    qty, unit = parse_number(ing.get("amount")), ing.get("unit")
    if qty is not None and unit:
        unit = unit.strip().lower()
        return qty, UNIT_ALIASES.get(unit, unit)
    text = nfc(ing.get("raw_text") or "") + " " + tail
    m = METRIC_RE.search(text)  # "250g (2 củ)": crawler bỏ sót vì có ngoặc
    if m:
        unit = m.group(2).lower()
        return parse_number(m.group(1)), UNIT_ALIASES.get(unit, unit)
    m = QTY_RE.search(text)
    if m and parse_number(m.group(1)) is not None:
        return parse_number(m.group(1)), "muỗng canh" if m.group(2) == "M" else "muỗng cà phê"
    return qty, None


def clean_ingredient(ing):
    """1 dòng thô -> list nguyên liệu sạch (thường 1, nhiều nếu dòng là danh sách 'tiêu, dầu ăn, muối')."""
    text = strip_noise(ing.get("raw_text") or ing.get("name") or "")
    role, text = split_prefix(text)
    head, tail = split_head_tail(text)
    parts = [p for p in re.split(r"[,;]| và ", head) if p.strip()]
    names = [n for p in parts for n in canonical(p)]
    # Nhiều nguyên liệu trong 1 dòng thì số lượng không gán cho riêng cái nào được.
    qty, unit = parse_quantity(ing, tail) if len(names) == 1 else (None, None)
    return [
        {"raw_text": ing.get("raw_text"), "name": n, "quantity": qty, "unit": unit, "role": role}
        for n in names
    ]


def main():
    recipes = json.loads(SRC.read_text(encoding="utf-8"))
    vocab = Counter()
    raw_lines = clean_lines = 0
    for r in recipes:
        r["id"] = r["url"].rstrip("/").rsplit("/", 1)[-1]
        cleaned = []
        for ing in r["ingredients"]:
            raw_lines += 1
            cleaned.extend(clean_ingredient(ing))
        r["ingredients"] = cleaned
        clean_lines += len(cleaned)
        vocab.update(i["name"] for i in cleaned)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8")
    with VOCAB.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "count"])
        w.writerows(vocab.most_common())

    long_names = [n for n in vocab if len(n) > 30]
    print(f"recipes: {len(recipes)} | raw lines: {raw_lines} -> clean lines: {clean_lines}")
    print(f"distinct names: {len(vocab)} | names >30 chars (nghi ngờ chưa sạch): {len(long_names)}")
    print("top 40:", vocab.most_common(40))
    print("sample long:", long_names[:10])


if __name__ == "__main__":
    main()
