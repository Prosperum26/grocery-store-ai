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
# Số lượng đứng đầu tên: "1 con cá điêu hồng" -> "cá điêu hồng", "1m rượu trắng" -> "rượu trắng"
LEAD_QTY_RE = re.compile(r"^[\d/.,½¼¾⅓⅔]+\s*(m|g|gr|kg|ml|con|quả|trái|củ|cây|miếng|gói)?(\s+|$)")
TRAIL_QTY_RE = re.compile(r"\s+-?\s*[\d½¼¾⅓⅔].*$")  # "bột rau câu dẻo -2g", "mía dài 40cm": cắt từ chỗ có số

# DẠNG DỄ LÀM TẠI NHÀ (phi, xay, rang): gộp về tên gốc, "tỏi phi" ghép như "tỏi". Dạng được
# ghi lại ở trường `form` để lúc ghép catalog vẫn thử tìm đúng dạng trước. Chỉ tìm ở các từ SAU
# từ đầu tiên của tên.
# Dạng KHÓ làm (khô, đông lạnh, đóng hộp, ngâm chua) là mặt hàng riêng nên KHÔNG tách:
# "tôm khô", "cà chua hộp", "dưa cải chua" giữ nguyên trong `name`.
FORM_PATTERNS = [
    (r"phi(?! lê)", "phi"),  # "phi lê" là philê cá/thịt, không phải hành phi
    (r"xay", "xay"),
    (r"rang", "rang"),
]
# DẠNG SƠ CHẾ / mô tả hình dạng: không đổi mặt hàng nên bỏ qua khi ghép.
IGNORE_WORDS = [
    "sợi", "lát", "hạt lựu", "cọng dài", "cọng", "nguyên con", "nguyên củ", "nguyên",
    "thật nhuyễn", "nhuyễn", "tép", "trái", "các loại", "mỗi loại", "tai", "búp", "chín đỏ", "chín",
    "còn vỏ", "không xương", "có xương", "lọc xương", "rút xương", "có dầu", "tươi sống",
    # bước sơ chế: bóc/bỏ phần không ăn, pha, ngâm nở, làm sạch...
    "bóc vỏ", "bỏ vỏ", "lột vỏ", "gọt vỏ", "tách vỏ", "bỏ hạt", "bỏ ruột", "bỏ đầu", "bỏ da",
    "không da", "bỏ xương", "chừa đuôi", "pha loãng", "ngâm nở", "đã ngâm nở", "ngâm nước",
    "đã sơ chế", "đã làm sạch", "rửa sạch", "làm sạch", "để chiên", "dùng ngay", "ăn kèm",
]
# Nướng chỉ là bước sơ chế với các loại củ/gia vị này; "bánh tráng nướng" là hàng riêng.
COOK_DROP_HEADS = ("hành", "gừng", "tỏi", "sả", "ớt")
# "tươi" là dạng mặc định nên bỏ, trừ các tên mà "tươi" là một phần tên hàng ("sữa tươi").
FRESH_PROTECTED = ("sữa tươi", "kem tươi", "nước dừa tươi")
# Màu giữ nguyên ("ớt đỏ" khác "ớt xanh", "tiêu xanh", "mè đen"). Chỉ "hành lá xanh" là
# cùng một mặt hàng với "hành lá" nên màu bị bỏ.
COLOR_WORDS = ["xanh đỏ", "đỏ", "xanh", "vàng"]
COLOR_DROP_HEADS = ("hành lá",)
# Mảnh vụn khi tách "ớt xanh, đỏ" bằng dấu phẩy. Màu rời được ghép lại với tên đứng trước
# (xem clean_ingredient), các mảnh khác thì bỏ.
FRAGMENTS ={"đỏ", "xanh", "vàng", "trắng", "non", "già", "lá", "củ", "trái", "hạt", "kg", "g", "gr", "ml"}
# Không phải hàng mua được: bỏ khỏi danh sách nguyên liệu.
NOT_PURCHASABLE = {"nước", "nước lọc", "nước sôi", "nước dùng", "món canh", "món xào",
                   "món chiên", "nhân", "gia vị", "tráng miệng", "vỏ"}

# Tên bắt đầu bằng cụm này thì gộp về tên gốc: "sả cây bỏ lá" -> "sả".
PREFIX_ALIASES = [("sả cây", "sả")]

# Đồng nghĩa/viết sai -> tên gốc. Giá trị là list nếu một tên gồm nhiều nguyên liệu.
ALIASES = {
    "cà hộp": "cà chua hộp", "cà paste hộp": "cà chua paste hộp", "cà paste": "cà chua paste",
    "tỏi củ": "tỏi", "gừng củ": "gừng",
    "thịt ba rọi": "thịt ba chỉ", "ba rọi": "thịt ba chỉ", "ba chỉ": "thịt ba chỉ",
    "mì gói": "mì", "mì ăn liền": "mì",
    # Tên quá chung: "thịt"/"thịt xay" trong công thức Việt hầu như là thịt heo, "hành" đứng
    # một mình thường là hành lá. Không gộp thì "thịt" khớp bừa "Thịt ốc bươu".
    "thịt": "thịt heo", "hành": "hành lá",
    "tỏi ớt": ["tỏi", "ớt"], "sả ớt": ["sả", "ớt"], "sả cây": "sả",
    "đậu hủ": "đậu hũ", "đậu hủ trắng": "đậu hũ", "đậu hũ trắng": "đậu hũ", "đậu phụ": "đậu hũ",
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
COUNT_QTY_RE = re.compile(
    r"(\d+(?:[.,/]\d+)?[½¼¾⅓⅔]?|[½¼¾⅓⅔])\s*"
    r"(quả|trái|củ|cây|chén|miếng|cái|nhánh|lá|con|gói|tép|hộp|ổ|tô|bó|lát|nắm|cọng)\b",
    re.IGNORECASE,
)


def nfc(s):
    """Chuẩn Unicode NFC và bỏ ký tự vô hình (zero-width) dính từ HTML crawl."""
    return re.sub("[​‌‍﻿]", "", unicodedata.normalize("NFC", s))


UNICODE_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}


def parse_number(s):
    """'200' -> 200.0, '1/2' -> 0.5, '1,5' -> 1.5, '½' -> 0.5, '1½' -> 1.5, không đọc được -> None."""
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if s and s[-1] in UNICODE_FRACTIONS:
        whole = float(s[:-1]) if s[:-1] else 0.0
        return whole + UNICODE_FRACTIONS[s[-1]]
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
    text = text.replace(")", " ")                 # ngoặc đóng mồ côi
    for sep in ("\t", ":"):
        if sep in text:
            head, tail = text.split(sep, 1)
            return head.strip(), tail.strip()
    # Không có dấu phân cách: cắt tại chỗ bắt đầu số lượng ("Hành tây 1/2 củ", "Tỏi băm 2M")
    m = re.search(r"\s[\d½¼¾⅓⅔]", text)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    return text.strip(), ""


def tidy(name):
    """Gọn khoảng trắng, bỏ dấu câu ở hai đầu (kể cả ':' đứng cuối như 'hành tây:')."""
    return re.sub(r"\s+", " ", name).strip(" .,;:-–&")


def extract_form(name):
    """'tỏi phi có dầu' -> ('tỏi có dầu', 'phi'). Chỉ xét các từ sau từ đầu tiên."""
    first, _, rest = name.partition(" ")
    form = None
    for pattern, value in FORM_PATTERNS:
        new_rest = re.sub(rf"\b{pattern}\b", " ", rest)
        if new_rest != rest:
            form, rest = form or value, new_rest
    return tidy(f"{first} {rest}"), form


def drop_descriptors(name):
    """Bỏ mô tả không đổi mặt hàng: hình dạng/sơ chế, 'tươi' (mặc định), màu ở các mặt hàng cho phép."""
    first, _, rest = name.partition(" ")
    if not name.startswith(FRESH_PROTECTED):
        rest = re.sub(r"\btươi\b", " ", rest)
    for word in sorted(IGNORE_WORDS, key=len, reverse=True):  # cụm dài trước: "ngâm nở" trước "nở"
        rest = re.sub(rf"\b{word}\b", " ", rest)
    if first.startswith(COOK_DROP_HEADS) or name.startswith(COOK_DROP_HEADS):
        rest = re.sub(r"\bnướng\b", " ", rest)
    name = tidy(f"{first} {rest}")
    if name.startswith(COLOR_DROP_HEADS):
        for word in COLOR_WORDS:
            name = re.sub(rf"\b{word}\b", " ", name)
    return tidy(name)


def canonical(name):
    """Một cụm tên -> list (tên gốc, dạng). List vì 'hành tỏi' tách thành 2; rỗng nếu không còn gì."""
    name = tidy(name.lower())
    name = LEAD_QTY_RE.sub("", name)
    name = TRAIL_QTY_RE.sub("", name)             # đuôi số lượng còn sót
    name = BRAND_CUT_RE.sub("", name)
    name = BRAND_DROP_RE.sub("", name)
    name = PREP_RE.sub("", name)
    name = SIZE_TAIL_RE.sub("", name)
    name, form = extract_form(tidy(name))
    name = drop_descriptors(name)
    if name in FRAGMENTS or name in NOT_PURCHASABLE or name.startswith("sản phẩm") or name[:1].isdigit():
        return []
    name = next((to for prefix, to in PREFIX_ALIASES if name.startswith(prefix)), name)
    mixed = re.fullmatch(r"(.+) xanh đỏ", name)  # "ớt hiểm xanh đỏ" = ớt xanh + ớt đỏ
    if mixed:
        return [(f"{mixed.group(1)} xanh", form), (f"{mixed.group(1)} đỏ", form)]
    alias = ALIASES.get(name, name)
    out = alias if isinstance(alias, list) else [alias]
    return [(n, form) for n in out if len(n) >= 2]


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
    m = COUNT_QTY_RE.search(tail)  # "½ trái", "2 củ": số đếm kèm đơn vị, chỉ tìm ở phần đuôi
    if m and parse_number(m.group(1)) is not None:
        unit = m.group(2).lower()
        return parse_number(m.group(1)), UNIT_ALIASES.get(unit, unit)
    return qty, None


def clean_ingredient(ing):
    """1 dòng thô -> list nguyên liệu sạch (thường 1, nhiều nếu dòng là danh sách 'tiêu, dầu ăn, muối')."""
    text = strip_noise(ing.get("raw_text") or ing.get("name") or "")
    role, text = split_prefix(text)
    head, tail = split_head_tail(text)
    items = []  # (name, form, alt): alt là các lựa chọn thay thế sau "/" hoặc "hoặc"
    for part in (p for p in re.split(r"[,;]| và |\.\s+", head) if p.strip()):
        first, *others = re.split(r"\s*/\s*| hoặc ", part)
        part_color = tidy(first.lower())
        if part_color in COLOR_WORDS and items:
            # "ớt xanh, đỏ": màu rời đi theo tên đứng trước -> thêm "ớt đỏ"
            base = re.sub(rf"\s+({'|'.join(COLOR_WORDS)})$", "", items[-1][0])
            items.append((f"{base} {part_color}", items[-1][1], []))
            continue
        alt = [n for o in others for n, _ in canonical(o)]
        items += [(n, form, alt) for n, form in canonical(first)]
    # Nhiều nguyên liệu trong 1 dòng thì số lượng không gán cho riêng cái nào được.
    # Ghép cả `head` vào để bắt số lượng đứng trước tên: "½ củ hành tây".
    qty, unit = parse_quantity(ing, f"{tail} {head}") if len(items) == 1 else (None, None)
    return [
        {"raw_text": ing.get("raw_text"), "name": n, "form": form, "quantity": qty, "unit": unit,
         "role": role, **({"alt": alt} if alt else {})}
        for n, form, alt in items
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
        vocab.update((i["name"], i["form"] or "") for i in cleaned)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8")
    with VOCAB.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "form", "count"])
        w.writerows((n, form, c) for (n, form), c in vocab.most_common())

    names = Counter()
    for (n, _), c in vocab.items():
        names[n] += c
    long_names = [n for n in names if len(n) > 30]
    forms = Counter(form for (_, form), c in vocab.items() for _ in range(c) if form)
    print(f"recipes: {len(recipes)} | raw lines: {raw_lines} -> clean lines: {clean_lines}")
    print(f"distinct (name, form): {len(vocab)} | distinct name: {len(names)} | names >30 chars: {len(long_names)}")
    print("forms:", dict(forms))
    print("top 40:", vocab.most_common(40))
    print("sample long:", long_names[:10])


if __name__ == "__main__":
    main()
