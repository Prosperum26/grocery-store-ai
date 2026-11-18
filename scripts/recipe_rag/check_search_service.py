"""Kiểm RecipeService (src/services/recipe_service.py) bằng bộ 108 câu có nhãn: Recall, từ chối đúng, độ trễ.

Chạy từ thư mục grocery-store-ai (cần ai_db đang chạy, đã load_recipes + embed_recipes + load_basket_data):
    .venv\\Scripts\\python scripts\\recipe_rag\\check_search_service.py

Phải cho kết quả khớp scripts/recipe_rag/eval_recipe_search.py (hybrid, Recall@5 ~0.99). Đây là cổng kiểm của GĐ 2
trong docs/recipe_rag/plan-ai-copilot.md: p95 < 1 giây và accepted/Recall không tệ hơn script đo.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))                       # để import được `src`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_recipe_search import is_relevant, toks     # noqa: E402  dùng đúng luật nhãn của script đo

from src.config.settings import get_settings         # noqa: E402
from src.ml.embedder import Embedder                  # noqa: E402
from src.schemas.recipe_dto import SearchRequest      # noqa: E402
from src.services.recipe_service import RecipeService  # noqa: E402


def main():
    queries = json.loads((ROOT / "data" / "recipe_rag" / "eval" / "recipe_queries_v1.json").read_text(encoding="utf-8"))["queries"]
    final = {r["id"]: r for r in json.loads((ROOT / "data" / "recipe_rag" / "final" / "recipes_v2.json").read_text(encoding="utf-8"))}
    name_tokens = {rid: toks(r["name"]) for rid, r in final.items()}
    ingr_tokens = {rid: [toks(b["ingredient"]) for b in r["basket"] if b["kind"] == "core"] for rid, r in final.items()}

    settings = get_settings()
    t0 = time.time()
    service = RecipeService(settings, Embedder(settings.embedding_model))
    print(f"khởi động service: {time.time() - t0:.1f}s | {len(service.recipes)} món, {len(service.catalog)} sản phẩm, ngưỡng {settings.search_threshold}")
    service.search(SearchRequest(query="canh chua"))   # chạy nóng một lần để không tính vào độ trễ

    found = reject = hit1 = hit5 = rej_ok = serve_ok = 0
    latencies, misses, false_accepts, bad_baskets = [], [], [], []
    for q in queries:
        start = time.perf_counter()
        resp = service.search(SearchRequest(query=q["query"], top_k=5))
        latencies.append((time.perf_counter() - start) * 1000)
        ids = [r.recipe.id for r in resp.results]
        for r in resp.results:                          # giỏ phải hợp lệ: số lượng mặc định đúng quy tắc
            if any(i.default_qty != 1 for i in r.basket.buy) or any(i.default_qty != 0 for i in r.basket.maybe_have):
                bad_baskets.append((q["id"], r.recipe.id))
        if q["expect"] == "found":
            found += 1
            rel = {rid for rid in final if is_relevant(q["relevant"], name_tokens[rid], ingr_tokens[rid])}
            rank = next((i for i, rid in enumerate(ids, 1) if rid in rel), None)
            hit1 += rank == 1
            hit5 += rank is not None
            serve_ok += rank is not None and resp.accepted
            if rank is None:
                misses.append((q["id"], q["query"], [r.recipe.name for r in resp.results[:2]]))
        else:
            reject += 1
            rej_ok += not resp.accepted
            if resp.accepted:
                false_accepts.append((q["id"], q["query"], resp.results[0].recipe.name if resp.results else None))
    lat = np.array(latencies)
    print(f"\n{len(queries)} câu: {found} có món đúng, {reject} nên từ chối")
    print(f"Recall@1 {hit1 / found:.2f} | Recall@5 {hit5 / found:.2f} | phục vụ đúng (có món đúng và accepted) {serve_ok / found:.2f} | từ chối đúng {rej_ok / reject:.2f}")
    print(f"độ trễ ms: p50 {np.percentile(lat, 50):.0f} | p95 {np.percentile(lat, 95):.0f} | max {lat.max():.0f}")
    print("trượt top-5:", misses)
    print("nhận nhầm (nên từ chối):", false_accepts)
    print("giỏ sai quy tắc số lượng mặc định:", bad_baskets[:5] or "không")


if __name__ == "__main__":
    main()
