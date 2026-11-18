from src.utils.text_cleaner import has_accents, keywords, name_matcher, split_servings, strip_accents, tokens, words


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


def test_words_keep_accents():
    assert words("Phở bò, 2 TÔ") == ["phở", "bò", "2", "tô"]
    assert has_accents("cơm chiên") and has_accents("đậu") and not has_accents("com chien 4 nguoi")


def test_accented_query_does_not_match_a_different_word():
    com_chien = name_matcher("cơm chiên")
    assert com_chien("Cơm chiên dừa") and not com_chien("Tôm chiên cốm")
    pho = name_matcher("phở bò")
    assert pho("Phở bò bắp hoa") and not pho("Khoai tây xào thịt bò phô mai") and not pho("Bò xào đậu phộng")
    assert name_matcher("canh chua")("Canh chua cá lóc") and not name_matcher("canh chua cá")("Cánh gà chua ngọt")


def test_unaccented_query_matches_any_accent():
    com_chien = name_matcher("com chien")
    assert com_chien("Cơm chiên dừa") and com_chien("Tôm chiên cốm")       # không dấu thì không phân biệt được
    assert name_matcher("bun rieu cua")("Bún riêu cua bắp bò")


def test_stopwords_are_dropped_and_goat_is_not_a_stopword():
    assert name_matcher("món gì cho người") is None and name_matcher("mon gi") is None
    assert name_matcher("món dê")("Lẩu dê") and not name_matcher("món dê")("Canh chua")   # "dê" bỏ dấu là "de" nhưng không phải từ thừa "để"
