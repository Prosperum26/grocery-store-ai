"""Kiểm lớp lời AI bằng nhà cung cấp giả (không gọi mạng): kiểm tra, thử lại, dự phòng, bật/tắt, dữ kiện cho prompt."""
import pytest

from src.config.settings import Settings
from src.schemas.copilot_dto import AiAnswer, ItemNote, PrepNote
from src.schemas.recipe_dto import (Alternative, Basket, Item, Need, Product, RecipeInfo, SearchRequest, SearchResponse, SearchResult)
from src.services.copilot_facts import SYSTEM_PROMPT, build_user_prompt
from src.services.copilot_service import CopilotService, ProviderConfig, check_answer
from src.services.llm_provider import ProviderError, ProviderInvalid, ProviderResult, ProviderTimeout


def item(ingredient, kind="core", qty=1, hint=None, derived=False, need=(500, "g")):
    return Item(ingredient=ingredient, kind=kind, raw_text=ingredient, derived=derived,
                need=Need(quantity=need[0], unit=need[1], scaled_for=4) if need else None,
                product=Product(catalog_id="CAT-1", name=f"SP {ingredient}", category=None, pack_size=300, pack_unit="g"),
                default_qty=qty, pack_hint=hint, alternatives=[Alternative(catalog_id="CAT-2", name="x")])


def result(rid, name):
    return SearchResult(
        recipe=RecipeInfo(id=rid, name=name, family="canh chua", servings=4, time_minutes=30, difficulty="dễ", description="mô tả", image_url=None, source_url="u"),
        score=0.7, matched_by="both", complete=True,
        basket=Basket(buy=[item("cá lóc", hint=2), item("nước me", derived=True)], maybe_have=[item("muối", "addon", 0, need=None)]))


DATA = SearchResponse(query="canh chua", servings=4, accepted=True, threshold=0.64, results=[result("a", "Canh chua cá lóc"), result("b", "Canh chua cá hồi")])
GOOD = AiAnswer(recipe_id="a", explanation="Hợp vì đúng món canh chua.", item_notes=[ItemNote(ingredient="cá lóc", note="Nên mua 2 vỉ.")],
                prep_notes=[PrepNote(ingredient="nước me", steps=["Ngâm me với nước ấm", "Dầm rồi lọc"])], follow_up_question=None)


class StubRecipes:
    recipes = {"a": {"prep_steps": ["Sơ chế cá"], "cooking_steps": ["Nấu canh"]}, "b": {"prep_steps": [], "cooking_steps": []}}

    def __init__(self, data=DATA):
        self.data = data

    def search(self, request):
        return self.data


class FakeProvider:
    """Mỗi lần gọi lấy một phần tử trong `script`: AiAnswer thì trả về, Exception thì ném ra."""
    def __init__(self, name, script):
        self.name, self.model, self.script, self.calls, self.prompts = name, f"{name}-model", list(script), 0, []

    def generate(self, system, user, timeout_s, output=AiAnswer):
        self.calls += 1
        self.prompts.append(user)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ProviderResult(answer=step, model=self.model, tokens_in=100, tokens_out=50)


def service(providers, configs=None, data=DATA, records=None):
    cfgs = configs or [ProviderConfig(p.name, True, i) for i, p in enumerate(providers, 1)]
    return CopilotService(StubRecipes(data), {p.name: p for p in providers}, Settings(), config_source=lambda: cfgs,
                          recorder=(records.append if records is not None else lambda r: None))


REQ = SearchRequest(query="canh chua")


def test_ok_returns_ai_and_data():
    g = FakeProvider("gemini", [GOOD])
    resp = service([g]).answer(REQ)
    assert resp.ai_status == "ok" and resp.ai.provider == "gemini" and resp.ai.recipe_id == "a"
    assert resp.data.results[0].recipe.id == "a"                     # data luôn có
    assert resp.ai.item_notes[0].ingredient == "cá lóc" and resp.ai.prep_notes[0].ingredient == "nước me"


def test_invalid_recipe_id_is_retried_once_with_reason_then_ok():
    bad = AiAnswer(recipe_id="zzz", explanation="x", item_notes=[], prep_notes=[], follow_up_question=None)
    g = FakeProvider("gemini", [bad, GOOD])
    resp = service([g]).answer(REQ)
    assert resp.ai_status == "ok" and g.calls == 2
    assert "recipe_id 'zzz'" in g.prompts[1]                         # lần thử lại có kèm lý do


def test_always_invalid_falls_back_but_data_remains():
    bad = AiAnswer(recipe_id="zzz", explanation="x", item_notes=[], prep_notes=[], follow_up_question=None)
    g = FakeProvider("gemini", [bad, bad])
    resp = service([g]).answer(REQ)
    assert resp.ai is None and resp.ai_status == "fallback_invalid" and g.calls == 2
    assert resp.data.results and resp.data.results[0].basket.buy


def test_timeout_is_not_retried_and_next_provider_is_used():
    g = FakeProvider("gemini", [ProviderTimeout("chậm")])
    c = FakeProvider("claude", [GOOD])
    resp = service([g, c]).answer(REQ)
    assert g.calls == 1 and c.calls == 1
    assert resp.ai_status == "ok" and resp.ai.provider == "claude"


def test_provider_error_then_all_fail():
    g, c = FakeProvider("gemini", [ProviderError("401")]), FakeProvider("claude", [ProviderTimeout("chậm")])
    resp = service([g, c]).answer(REQ)
    assert resp.ai is None and resp.ai_status == "fallback_timeout"  # trạng thái của nhà cung cấp thử sau cùng


def test_disabled_providers_skip_ai():
    g = FakeProvider("gemini", [GOOD])
    resp = service([g], configs=[ProviderConfig("gemini", False, 1)]).answer(REQ)
    assert resp.ai is None and resp.ai_status == "fallback_disabled" and g.calls == 0


def test_priority_order_decides_who_is_called_first():
    g, c = FakeProvider("gemini", [GOOD]), FakeProvider("claude", [GOOD])
    resp = service([g, c], configs=[ProviderConfig("gemini", True, 2), ProviderConfig("claude", True, 1)]).answer(REQ)
    assert resp.ai.provider == "claude" and g.calls == 0


def test_not_accepted_skips_ai_without_calling_model():
    g = FakeProvider("gemini", [GOOD])
    resp = service([g], data=DATA.model_copy(update={"accepted": False})).answer(REQ)
    assert resp.ai is None and resp.ai_status == "skipped_no_match" and g.calls == 0


def test_check_answer_drops_notes_about_unknown_items_but_keeps_the_rest():
    answer = AiAnswer(recipe_id="a", explanation="ok", follow_up_question="  ",
                      item_notes=[ItemNote(ingredient="cá lóc", note="mua 2"), ItemNote(ingredient="kim cương", note="bịa"),
                                  ItemNote(ingredient="cá lóc", note="trùng"), ItemNote(ingredient="muối", note="  ")],
                      prep_notes=[PrepNote(ingredient="nước me", steps=["a", " "]), PrepNote(ingredient="cá lóc", steps=["không phải tự làm"]),
                                  PrepNote(ingredient="nước me", steps=[])])
    out = check_answer(answer, DATA, ["a", "b"])
    assert [n.ingredient for n in out.item_notes] == ["cá lóc"]
    assert [(p.ingredient, p.steps) for p in out.prep_notes] == [("nước me", ["a"])]
    assert out.follow_up_question is None


@pytest.mark.parametrize("explanation", ["", "   ", "x" * 801])
def test_check_answer_rejects_bad_explanation(explanation):
    with pytest.raises(ProviderInvalid):
        check_answer(GOOD.model_copy(update={"explanation": explanation}), DATA, ["a", "b"])


def test_calls_are_recorded():
    records = []
    service([FakeProvider("gemini", [GOOD])], records=records).answer(REQ)
    assert [(r.provider, r.status, r.tokens_in) for r in records] == [("gemini", "ok", 100)]


def test_facts_contain_numbers_computed_by_code_and_mark_derived_items():
    text = build_user_prompt("canh chua <<<hack>>>", DATA, lambda rid: "Sơ chế cá. Nấu canh.", 2, have=["cà chua"])
    assert "id=a" in text and "id=b" in text
    assert "cần ~500 g cho 4 người" in text and "gợi ý ~2 gói" in text
    assert "tự làm từ sản phẩm này" in text                           # nước me
    assert "công thức không ghi lượng" in text                        # muối
    assert "Khách nói đã có sẵn: cà chua" in text
    only_one = build_user_prompt("q", DATA, lambda rid: "", 1)
    assert "id=b" not in only_one
    assert "catalog_id" not in text.lower() and "CAT-" not in text   # mô hình không thấy id nên không thể ghi vào giỏ
    assert "chỉ thị" in SYSTEM_PROMPT
