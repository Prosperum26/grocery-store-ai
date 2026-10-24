"""Kiểm tích hợp RecipeService với ai_db thật. Bỏ qua nếu DB hoặc model chưa sẵn sàng."""
import pytest

from src.config.settings import get_settings
from src.schemas.recipe_dto import SearchRequest


@pytest.fixture(scope="module")
def service():
    try:
        from src.ml.embedder import Embedder
        from src.services.recipe_service import RecipeService
        settings = get_settings()
        return RecipeService(settings, Embedder(settings.embedding_model))
    except Exception as e:                                   # DB tắt, thiếu model, chưa nạp bảng...
        pytest.skip(f"chưa có ai_db hoặc model: {e.__class__.__name__}")


def test_exact_dish_is_top1_and_accepted(service):
    resp = service.search(SearchRequest(query="canh chua cá lóc cho 4 người"))
    assert resp.accepted and resp.servings == 4
    assert resp.results[0].recipe.name.lower() == "canh chua cá lóc"
    assert resp.results[0].complete and resp.results[0].basket.buy


def test_no_accent_query_finds_dish(service):
    resp = service.search(SearchRequest(query="bun rieu cua"))
    assert resp.accepted and "bún riêu" in resp.results[0].recipe.name.lower()


def test_off_topic_is_not_accepted_but_returns_nearest(service):
    resp = service.search(SearchRequest(query="điện thoại iphone 15"))
    assert not resp.accepted and resp.results


def test_servings_scale_changes_need(service):
    two = service.search(SearchRequest(query="canh chua cá lóc", servings=2)).results[0]
    six = service.search(SearchRequest(query="canh chua cá lóc", servings=6)).results[0]
    a = next(i for i in two.basket.buy if i.need)
    b = next(i for i in six.basket.buy if i.ingredient == a.ingredient)
    assert b.need.quantity == pytest.approx(a.need.quantity * 3)


def test_default_quantities(service):
    for r in service.search(SearchRequest(query="gà nướng", top_k=5)).results:
        assert all(i.default_qty == 1 for i in r.basket.buy)
        assert all(i.default_qty == 0 for i in r.basket.maybe_have)
