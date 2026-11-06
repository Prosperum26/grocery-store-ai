"""Recipe service: tìm món (từ khóa + embedding) và dựng giỏ hàng hai phần.

Tìm món rồi gọi build_basket (services/basket.py). Kết quả luôn do code dựng; không có mô hình ngôn ngữ ở đây.
"""
import psycopg
from pgvector.psycopg import register_vector

from src.config.settings import Settings
from src.ml.embedder import Embedder
from src.schemas.recipe_dto import RecipeInfo, SearchRequest, SearchResponse, SearchResult
from src.services.basket import BASE_UNIT, build_basket, pack_hint  # noqa: F401  (giữ import cũ chạy được)
from src.utils.text_cleaner import keywords, split_servings, tokens

KEYWORD_LIMIT = 10


class RecipeService:
    """Giữ sẵn model, danh sách món và catalog trong bộ nhớ; mỗi lần tìm chỉ mở một kết nối DB ngắn."""

    def __init__(self, settings: Settings, embedder: Embedder):
        self.settings = settings
        self.embedder = embedder
        with self._connect() as conn:
            rows = conn.execute(
                """select r.id, r.name, r.source_url, r.image_url, r.description, r.servings, r.time_minutes, r.difficulty,
                          r.prep_steps, r.cooking_steps, b.family, b.complete, b.ingredients
                   from recipe r join recipe_basket b on b.recipe_id = r.id order by r.id""").fetchall()
            catalog_rows = conn.execute("select catalog_id, name, category, unit, pack_size, pack_unit from catalog_product").fetchall()
        cols = ["id", "name", "source_url", "image_url", "description", "servings", "time_minutes", "difficulty", "prep_steps", "cooking_steps", "family", "complete", "ingredients"]
        self.recipes = {r[0]: dict(zip(cols, r)) for r in rows}
        self.ids = list(self.recipes)
        self.name_tokens = {rid: tokens(r["name"]) for rid, r in self.recipes.items()}
        self.catalog = {c[0]: dict(zip(["catalog_id", "name", "category", "unit", "pack_size", "pack_unit"], c)) for c in catalog_rows}

    def _connect(self) -> psycopg.Connection:
        s = self.settings
        conn = psycopg.connect(host=s.ai_db_host, port=s.ai_db_port, dbname=s.ai_db_name, user=s.ai_db_user,
                               password=s.ai_db_password.get_secret_value(), connect_timeout=5)
        register_vector(conn)
        return conn

    def _keyword_hits(self, text: str) -> list[str]:
        """Món mà tên chứa mọi từ khóa (đã bỏ dấu, bỏ từ thừa); tên ngắn xếp trước."""
        words = keywords(text)
        if not words:
            return []
        hits = [rid for rid in self.ids if all(w in self.name_tokens[rid] for w in words)]
        return sorted(hits, key=lambda rid: (len(self.recipes[rid]["name"]), rid))[:KEYWORD_LIMIT]

    def _semantic_hits(self, vec, limit: int) -> list[tuple[str, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                """select recipe_id, 1 - (embedding <=> %s) from recipe_embedding
                   where chunk_type = 'card' and recipe_id = any(%s) order by embedding <=> %s limit %s""",
                (vec, self.ids, vec, limit)).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def _card_similarities(self, vec, recipe_ids: list[str]) -> dict[str, float]:
        """Điểm embedding của các món cụ thể (món khớp từ khóa nhưng nằm ngoài top embedding)."""
        if not recipe_ids:
            return {}
        with self._connect() as conn:
            rows = conn.execute("select recipe_id, 1 - (embedding <=> %s) from recipe_embedding where chunk_type = 'card' and recipe_id = any(%s)",
                                (vec, recipe_ids)).fetchall()
        return {r[0]: float(r[1]) for r in rows}

    def search(self, request: SearchRequest) -> SearchResponse:
        text, servings_in_query = split_servings(request.query)
        text = text or request.query
        vec = self.embedder.encode(text)                      # embed một lần cho cả hai bước dưới
        semantic = self._semantic_hits(vec, max(10, request.top_k))
        sims = dict(semantic)
        lexical = self._keyword_hits(text)
        sims.update(self._card_similarities(vec, [rid for rid in lexical[:request.top_k] if rid not in sims]))
        in_semantic = {rid for rid, _ in semantic}
        # Món khớp từ khóa xếp trước, rồi tới món của embedding. Nhận kết quả nếu có món khớp từ khóa hoặc sim top-1 đủ cao.
        order = lexical + [rid for rid, _ in semantic if rid not in lexical]
        accepted = bool(lexical) or (bool(semantic) and semantic[0][1] >= self.settings.search_threshold)
        results = []
        for rid in order[:request.top_k]:
            r = self.recipes[rid]
            recipe_servings = r["servings"] or self.settings.search_default_servings
            servings = request.servings or servings_in_query or recipe_servings
            sim = sims.get(rid, 0.0)
            results.append(SearchResult(
                recipe=RecipeInfo(id=rid, name=r["name"], family=r["family"], servings=recipe_servings, time_minutes=r["time_minutes"],
                                  difficulty=r["difficulty"], description=r["description"], image_url=r["image_url"], source_url=r["source_url"]),
                score=round(sim, 4), matched_by=("both" if rid in lexical and rid in in_semantic else "keyword" if rid in lexical else "semantic"),
                complete=r["complete"],
                basket=build_basket(r["ingredients"], self.catalog, recipe_servings, servings, request.have)))
        servings_shown = request.servings or servings_in_query or (results[0].recipe.servings if results else self.settings.search_default_servings)
        return SearchResponse(query=text, servings=servings_shown, accepted=accepted, threshold=self.settings.search_threshold, results=results)
