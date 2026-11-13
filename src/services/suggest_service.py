"""Gợi ý món bằng luật trên dữ liệu công thức đã ghép với catalog. Không mô hình ngôn ngữ, không embedding.

Ba chế độ (spec docs/plans/2026-11-11-recipe-suggestions-spec.md của repo frontend):
  - by_products(mode="cart")     B: từ các sản phẩm trong giỏ, món nào giỏ đã phủ nhiều phần "đặc trưng" nhất.
  - by_products(mode="product")  C: từ một sản phẩm, món mà sản phẩm đó là nguyên liệu chính.
  - discover                     A: món có vài nguyên liệu khách chưa từng mua, chọn ổn định theo (khách, ngày).

Mọi ngưỡng ở đầu file là giá trị khởi đầu, chỉnh sau khi xem kết quả thật.
"""
import hashlib
import math

from src.schemas.recipe_dto import RecipeInfo
from src.schemas.suggest_dto import Matched, Suggestion
from src.services.basket import build_basket
from src.services.recipe_detail import recipe_info

MIN_CORE = 3               # món có ít hơn số nguyên liệu core này quá ngắn để gợi ý
MAX_CORE = 12              # nhiều hơn thì quá nặng để mua một lúc
STAPLE_SHARE = 0.15        # sản phẩm có mặt ở từng này tỉ lệ món là "đồ nền" (hành tây, ớt...): không nói lên khách muốn nấu gì
TRY_NEW = (2, 4)           # bậc 1 của A: số nguyên liệu khách chưa từng mua
TRY_FAMILIAR = (1, 2)      # bậc 1 của A: số nguyên liệu khách đã quen
FIRST_CORE = 2             # C: sản phẩm nằm trong từng này nguyên liệu core đầu thì coi là nguyên liệu chính


class SuggestService:
    """Dựng chỉ mục một lần từ `recipes` và `catalog` của RecipeService (cả hai nằm sẵn trong bộ nhớ)."""

    def __init__(self, recipes: dict[str, dict], catalog: dict[str, dict], default_servings: int,
                 in_target: set[str] | None = None, needs_review: set[str] | None = None, skip_needs_review: bool = False):
        self.recipes = recipes
        self.catalog = catalog
        self.default_servings = default_servings
        self.in_target = in_target if in_target is not None else {rid for rid, r in recipes.items() if r.get("in_target_set")}
        # Spec ban đầu loại món có sản phẩm needs_review (tên, đơn vị tạm). Đo trên dữ liệu thật: loại thì chỉ còn 158/1061 món,
        # bỏ điều kiện này thì 1025/1061. /search đã hiện các sản phẩm đó cho khách nên mặc định không loại; đổi bằng skip_needs_review.
        review = (needs_review if needs_review is not None else {cid for cid, c in catalog.items() if c.get("needs_review")}) if skip_needs_review else set()

        # core_of: nguyên liệu core đã ghép của món, theo thứ tự công thức, mỗi sản phẩm một lần.
        # names_of: catalog_id -> tên nguyên liệu trong công thức đó (để câu dẫn nói "cá lóc", không nói "Cá lóc phi lê 500g").
        self.core_of: dict[str, list[str]] = {}
        self.names_of: dict[str, dict[str, str]] = {}
        for rid, recipe in recipes.items():
            core, names = [], {}
            for line in recipe["ingredients"]:
                if line["kind"] != "core" or line["status"] != "da_ghep":
                    continue
                cid = line["match"]["catalog_id"]
                if cid not in names:
                    core.append(cid)
                    names[cid] = line["ingredient"]
            self.core_of[rid] = core
            self.names_of[rid] = names

        # Món đủ điều kiện: đủ dài, không quá dài, không có sản phẩm đã mất khỏi catalog (và sản phẩm needs_review nếu skip_needs_review).
        self.eligible = sorted(
            rid for rid, recipe in recipes.items()
            if recipe["complete"] and MIN_CORE <= len(self.core_of[rid]) <= MAX_CORE
            and all(cid in catalog and cid not in review for cid in self.core_of[rid]))

        df: dict[str, int] = {}
        for rid in self.eligible:
            for cid in self.core_of[rid]:
                df[cid] = df.get(cid, 0) + 1
        n = len(self.eligible)
        # Trọng số ln(N/df): sản phẩm hiếm nói nhiều hơn. Đồ nền có trọng số 0.
        self.weight = {cid: (0.0 if n == 0 or count >= STAPLE_SHARE * n else math.log(n / count)) for cid, count in df.items()}

    # ---- B và C ----------------------------------------------------------------------------------------------

    def by_products(self, catalog_ids: list[str], mode: str, limit: int, have: list[str], exclude_ids: list[str]) -> list[Suggestion]:
        given = set(catalog_ids)
        skip = set(exclude_ids)
        pool = [rid for rid in self.eligible if rid not in skip and given & set(self.core_of[rid])]
        if mode == "cart":
            ranked = self._rank_cart(pool, given)
        else:
            ranked = self._rank_product(pool, given)
        return [self._suggestion(rid, have, matched=sorted(given & set(self.core_of[rid]), key=self.core_of[rid].index))
                for rid in self._one_per_family(ranked, limit)]

    def _rank_cart(self, pool: list[str], given: set[str]) -> list[str]:
        """Điểm = phần trọng số của món mà giỏ đã phủ. Chỉ khớp đồ nền (trọng số 0) thì bỏ."""
        scored = []
        for rid in pool:
            core = self.core_of[rid]
            matched_weight = sum(self.weight[c] for c in core if c in given)
            total_weight = sum(self.weight[c] for c in core)
            if matched_weight == 0 or total_weight == 0:
                continue
            missing = sum(1 for c in core if c not in given)
            scored.append((-matched_weight / total_weight, missing, rid not in self.in_target, rid))
        return [s[-1] for s in sorted(scored)]

    def _rank_product(self, pool: list[str], given: set[str]) -> list[str]:
        """C: không dùng trọng số (sản phẩm đồ nền vẫn phải có kết quả). Nguyên liệu chính trước, rồi món gọn."""
        def key(rid: str):
            main = any(c in given for c in self.core_of[rid][:FIRST_CORE])
            return (not main, len(self.core_of[rid]), rid not in self.in_target, rid)
        return sorted(pool, key=key)

    # ---- A ---------------------------------------------------------------------------------------------------

    def discover(self, bought: list[str], have: list[str], seed: str, limit: int, exclude_ids: list[str]) -> list[Suggestion]:
        owned = set(bought)
        in_cart = set(have)
        skip = set(exclude_ids)
        pool = [rid for rid in self.eligible if rid not in skip and not set(self.core_of[rid]) <= in_cart]

        if owned:
            def counts(rid: str) -> tuple[int, int]:
                core = set(self.core_of[rid])
                return len(core - owned), len(core & owned)
            tier1 = [rid for rid in pool if TRY_NEW[0] <= counts(rid)[0] <= TRY_NEW[1] and TRY_FAMILIAR[0] <= counts(rid)[1] <= TRY_FAMILIAR[1]]
            tier2 = [rid for rid in pool if 1 <= counts(rid)[0] <= 6]
            chosen = tier1 or tier2 or pool
        else:
            chosen = [rid for rid in pool if rid in self.in_target]     # khách chưa có lịch sử: chỉ món đã kiểm kỹ nhất

        ordered = sorted(chosen, key=lambda rid: hashlib.sha1(f"{seed}:{rid}".encode()).hexdigest())
        out = []
        for rid in self._one_per_family(ordered, limit):
            core = set(self.core_of[rid])
            suggestion = self._suggestion(rid, have, matched=[])
            suggestion.new_count, suggestion.familiar_count = len(core - owned), len(core & owned)
            out.append(suggestion)
        return out

    # ---- chung -----------------------------------------------------------------------------------------------

    def _one_per_family(self, ordered: list[str], limit: int) -> list[str]:
        """Lấy lần lượt, bỏ món cùng họ với món đã lấy để các món khác nhau. Món không có họ coi là một họ riêng."""
        picked, families = [], set()
        for rid in ordered:
            family = self.recipes[rid]["family"] or rid
            if family in families:
                continue
            families.add(family)
            picked.append(rid)
            if len(picked) == limit:
                break
        return picked

    def _suggestion(self, rid: str, have: list[str], matched: list[str]) -> Suggestion:
        recipe = self.recipes[rid]
        servings = recipe["servings"] or self.default_servings
        basket = build_basket(recipe["ingredients"], self.catalog, servings, servings, have)
        info: RecipeInfo = recipe_info(recipe, servings)
        return Suggestion(recipe=info, matched=[Matched(catalog_id=c, name=self.names_of[rid][c]) for c in matched],
                          missing_count=len(basket.buy), basket=basket)
