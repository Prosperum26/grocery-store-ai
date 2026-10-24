"""Chuẩn hóa văn bản câu hỏi: bỏ dấu, tách từ, tách số người ăn."""
import re
import unicodedata

# Từ không mang nghĩa món khi so khớp từ khóa ("món gà nướng cho 4 người" -> "ga nuong").
STOPWORDS = {"mon", "voi", "co", "va", "cho", "nguoi", "nau", "gi", "tu", "cach", "lam", "de", "mot", "nhung", "hay"}
_SERVINGS_RE = re.compile(r"\b(?:cho\s+)?(\d+)\s*(?:người|nguoi)\b", re.IGNORECASE)


def strip_accents(text: str) -> str:
    """'Canh chua cá lóc' -> 'canh chua ca loc' (đ -> d, chữ thường)."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokens(text: str) -> list[str]:
    """Danh sách từ không dấu, chỉ chữ và số."""
    return re.findall(r"[a-z0-9]+", strip_accents(text))


def keywords(text: str) -> list[str]:
    """Từ khóa để so khớp tên món: bỏ dấu, bỏ từ thừa."""
    return [w for w in tokens(text) if w not in STOPWORDS]


def split_servings(query: str) -> tuple[str, int | None]:
    """'món nướng cho 4 người' -> ('món nướng', 4). Số người là khẩu phần, không phải tên món."""
    m = _SERVINGS_RE.search(query)
    if not m:
        return query.strip(), None
    return (query[:m.start()] + " " + query[m.end():]).strip(" ,."), int(m.group(1))
