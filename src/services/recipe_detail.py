"""Chi tiết một món: thông tin, các bước nấu, giỏ nguyên liệu theo số người. Hàm thuần, không đụng DB hay model."""
from src.schemas.recipe_dto import RecipeDetailResponse, RecipeInfo
from src.services.basket import build_basket


def recipe_info(recipe: dict, servings: int) -> RecipeInfo:
    """`recipe` là một hàng của RecipeService.recipes; `servings` là khẩu phần của công thức."""
    return RecipeInfo(id=recipe["id"], name=recipe["name"], family=recipe["family"], servings=servings, time_minutes=recipe["time_minutes"],
                      difficulty=recipe["difficulty"], description=recipe["description"], image_url=recipe["image_url"], source_url=recipe["source_url"])


def build_recipe_detail(recipe: dict, catalog: dict[str, dict], servings: int | None, have: list[str], default_servings: int) -> RecipeDetailResponse:
    recipe_servings = recipe["servings"] or default_servings
    shown = servings or recipe_servings
    basket = build_basket(recipe["ingredients"], catalog, recipe_servings, shown, have)
    in_basket = {item.ingredient for item in basket.buy + basket.maybe_have}
    # Dòng không vào giỏ vẫn hiện cho khách đọc đủ công thức (đồ ăn kèm, hoặc cửa hàng chưa có sản phẩm tương ứng).
    not_in_basket = [line["raw_text"] for line in recipe["ingredients"] if line["ingredient"] not in in_basket]
    return RecipeDetailResponse(recipe=recipe_info(recipe, recipe_servings), servings=shown, complete=recipe["complete"],
                                prep_steps=list(recipe["prep_steps"] or []), cooking_steps=list(recipe["cooking_steps"] or []),
                                basket=basket, not_in_basket=not_in_basket)
