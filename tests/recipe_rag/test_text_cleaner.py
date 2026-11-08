from src.utils.text_cleaner import keywords, split_servings, strip_accents, tokens


def test_strip_accents():
    assert strip_accents("Canh chua cá lóc") == "canh chua ca loc"
    assert strip_accents("Đậu hũ") == "dau hu"


def test_tokens_and_keywords_drop_stopwords():
    assert tokens("Gà kho gừng, 4 người") == ["ga", "kho", "gung", "4", "nguoi"]
    assert keywords("món gà nướng cho 4 người") == ["ga", "nuong", "4"]


def test_split_servings():
    assert split_servings("món nướng cho 4 người") == ("món nướng", 4)
    assert split_servings("canh chua cá lóc") == ("canh chua cá lóc", None)
    assert split_servings("ga kho gung cho 6 nguoi") == ("ga kho gung", 6)
