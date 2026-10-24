"""Recipe service: tìm món (từ khóa + embedding) và dựng giỏ hàng hai phần.

Ba lớp, tách để kiểm riêng:
  - build_basket(): hàm thuần, không đụng DB. Nhân khẩu phần, chia phần buy / maybe_have, tính pack_hint.
  - RecipeService.search(): tìm món rồi gọi build_basket.
  - Kết quả luôn do code dựng; không có mô hình ngôn ngữ ở đây.
"""
import math

import psycopg
from pgvector.psycopg import register_vector

from src.config.settings import Settings
from src.ml.embedder import Embedder
from src.schemas.recipe_dto import (Alternative, Basket, Item, Need, Product, RecipeInfo, SearchRequest, SearchResponse,
                                    SearchResult)
from src.utils.text_cleaner import keywords, split_servings, strip_accents, tokens

# Đơn vị khối lượng / thể tích đổi được về đơn vị gốc: (loại, hệ số). Đơn vị khác (quả, củ, muỗng) không quy đổi.
BASE_UNIT = {"g": ("w", 1), "kg": ("w", 1000), "ml": ("v", 1), "lít": ("v", 1000)}
KEYWORD_LIMIT = 10


def pack_hint(quantity: float | None, unit: str | None, product: Product) -> int | None:
    """Số gói gợi ý = làm tròn lên (lượng cần / quy cách). Chỉ khi cùng loại đơn vị (g/kg hoặc ml/lít), ngược lại None."""
    if quantity is None or unit not in BASE_UNIT or product.pack_unit not in BASE_UNIT or not product.pack_size:
        return None
    (kind_a, factor_a), (kind_b, factor_b) = BASE_UNIT[unit], BASE_UNIT[product.pack_unit]
    if kind_a != kind_b:
        return None
    return max(1, math.ceil(quantity * factor_a / (float(product.pack_size) * factor_b)))


def build_basket(lines: list[dict], catalog: dict[str, dict], recipe_servings: int, servings: int,
                 have: list[str] | None = None) -> Basket:
    """Dựng giỏ hai phần từ các dòng nguyên liệu đã ghép của một món.

    lines: ingredients của recipe_basket. catalog: catalog_id -> hàng catalog_product.
    Nguyên liệu chính (core) vào buy với số lượng 1; đồ trong tủ bếp (addon) và đồ khách đã có vào maybe_have với 0.
    Dòng side, dòng bị bỏ khỏi giỏ và dòng chưa ghép được không vào giỏ. Cùng nguyên liệu xuất hiện nhiều dòng thì gộp.
    """
    factor = servings / recipe_servings
    have_norm = {strip_accents(h).strip() for h in (have or [])}
    by_ingredient: dict[str, dict] = {}
    for line in lines:
        if line["status"] != "da_ghep" or line["kind"] == "side":
            continue
        entry = by_ingredient.get(line["ingredient"])
        if entry is None:
            by_ingredient[line["ingredient"]] = {"line": line, "quantity": line["quantity"], "unit": line["unit"]}
        elif entry["quantity"] is not None and line["quantity"] is not None and entry["unit"] == line["unit"]:
            entry["quantity"] += line["quantity"]          # cùng đơn vị thì cộng dồn ("hành lá 20g" + "hành lá 10g")
    buy, maybe = [], []
    for ingredient, entry in by_ingredient.items():
        line, match = entry["line"], entry["line"]["match"]
        row = catalog.get(match["catalog_id"])
        if row is None:                                       # sản phẩm không còn trong catalog: bỏ, không đoán
            continue
        product = Product(catalog_id=row["catalog_id"], name=row["name"], category=row["category"],
                          pack_size=float(row["pack_size"]) if row["pack_size"] is not None else None, pack_unit=row["pack_unit"])
        quantity = entry["quantity"]
        need = Need(quantity=round(quantity * factor, 2), unit=entry["unit"], scaled_for=servings) if quantity is not None else None
        owned = strip_accents(ingredient) in have_norm or product.catalog_id.lower() in have_norm
        is_core = line["kind"] == "core" and not owned
        item = Item(ingredient=ingredient, kind=line["kind"], raw_text=line["raw_text"], need=need, product=product,
                    derived=match.get("match_via") == "quyet_dinh_che_bien_tu", default_qty=1 if is_core else 0,
                    pack_hint=pack_hint(need.quantity, need.unit, product) if need else None,
                    alternatives=[Alternative(catalog_id=a["catalog_id"], name=a["product_name"]) for a in match["alternatives"]])
        (buy if is_core else maybe).append(item)
    return Basket(buy=buy, maybe_have=maybe)


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
