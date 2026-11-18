"""Chuẩn hóa văn bản câu hỏi: bỏ dấu, tách từ, tách số người ăn."""
import re
import unicodedata

# Từ không mang nghĩa món khi so khớp từ khóa ("món gà nướng cho 4 người" -> "gà nướng").
STOPWORDS_ACCENTED = {"món", "với", "có", "và", "cho", "người", "nấu", "gì", "từ", "cách", "làm", "để", "một", "những", "hay"}
STOPWORDS = {"mon", "voi", "co", "va", "cho", "nguoi", "nau", "gi", "tu", "cach", "lam", "de", "mot", "nhung", "hay"}   # bản không dấu
_SERVINGS_RE = re.compile(r"\b(?:cho\s+)?(\d+)\s*(?:người|nguoi)\b", re.IGNORECASE)


def strip_accents(text: str) -> str:
    """'Canh chua cá lóc' -> 'canh chua ca loc' (đ -> d, chữ thường)."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokens(text: str) -> list[str]:
    """Danh sách từ không dấu, chỉ chữ và số."""
    return re.findall(r"[a-z0-9]+", strip_accents(text))


def words(text: str) -> list[str]:
    """Danh sách từ GIỮ dấu, chữ thường, chỉ chữ và số ('Phở bò' -> ['phở', 'bò'])."""
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text.lower()))


def has_accents(text: str) -> bool:
    """Khách có gõ dấu tiếng Việt không (kể cả chữ đ)."""
    return unicodedata.normalize("NFC", text.lower()) != strip_accents(text)


def keywords(text: str) -> list[str]:
    """Từ khóa không dấu để so khớp tên món: bỏ dấu, bỏ từ thừa."""
    return [w for w in tokens(text) if w not in STOPWORDS]


def name_matcher(query: str):
    """Trả hàm kiểm một tên món có chứa mọi từ khóa của câu hỏi không; None khi câu hỏi không còn từ khóa nào.

    Khách gõ CÓ dấu thì so từng từ có dấu: "cơm" không khớp "cốm", "phở" không khớp "phô (mai)".
    Khách gõ KHÔNG dấu ("com chien") thì hai bên cùng bỏ dấu, vì không biết họ muốn từ nào.
    """
    if has_accents(query):
        wanted = [w for w in words(query) if w not in STOPWORDS_ACCENTED]
        split = words
    else:
        wanted = keywords(query)
        split = tokens
    if not wanted:
        return None
    return lambda name: all(w in split(name) for w in wanted)


def split_servings(query: str) -> tuple[str, int | None]:
    """'món nướng cho 4 người' -> ('món nướng', 4). Số người là khẩu phần, không phải tên món."""
    m = _SERVINGS_RE.search(query)
    if not m:
        return query.strip(), None
    return (query[:m.start()] + " " + query[m.end():]).strip(" ,."), int(m.group(1))
