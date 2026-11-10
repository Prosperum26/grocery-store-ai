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
    lines = recipe["ingredients"]
    covered = {name for item in basket.buy + basket.maybe_have for name in item.ingredients}
    # Một dòng công thức có thể tách thành nhiều nguyên liệu ("đường, muối, nước mắm"): đếm để biết dòng nào bị tách.
    parts: dict[str, int] = {}
    for line in lines:
        parts[line["raw_text"]] = parts.get(line["raw_text"], 0) + 1
    # Phần không vào giỏ vẫn hiện cho khách (đồ ăn kèm, không phải hàng mua). Dòng nguyên vẹn thì ghi đúng chữ công thức;
    # dòng bị tách thì chỉ ghi tên nguyên liệu bị thiếu, để không lặp lại cả dòng.
    missing = [line["raw_text"] if parts[line["raw_text"]] == 1 else line["ingredient"] for line in lines if line["ingredient"] not in covered]
    not_in_basket = list(dict.fromkeys(missing))
    ingredient_lines = list(dict.fromkeys(line["raw_text"] for line in lines))
    return RecipeDetailResponse(recipe=recipe_info(recipe, recipe_servings), servings=shown, complete=recipe["complete"],
                                prep_steps=list(recipe["prep_steps"] or []), cooking_steps=list(recipe["cooking_steps"] or []),
                                basket=basket, ingredient_lines=ingredient_lines, not_in_basket=not_in_basket)
