"""Đo lớp lời AI bằng nhà cung cấp thật trên bộ câu hỏi có nhãn (data/recipe_rag/eval/recipe_queries_v1.json).

Chạy từ thư mục grocery-store-ai (cần ai_db chạy và khóa trong .env). MỖI CÂU TỐN MỘT LẦN GỌI THẬT:
    .venv\\Scripts\\python scripts\\recipe_rag\\eval_copilot.py --provider openrouter --limit 20
    .venv\\Scripts\\python scripts\\recipe_rag\\eval_copilot.py --provider openrouter            # toàn bộ câu 'found'

Đo: tỉ lệ ai_status=ok, số lần phải thử lại, độ trễ, token, và món AI chọn có đúng nhãn không (so với top-1 của tìm kiếm).
Câu 'reject' không gọi mô hình (skipped_no_match) nên không tính vào chi phí. Kết quả ghi vào data/recipe_rag/review/.
"""
import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_recipe_search import is_relevant, toks                    # noqa: E402  (dùng lại đúng cách xét "món đúng")
from src.config.settings import get_settings                        # noqa: E402
from src.ml.embedder import Embedder                                 # noqa: E402
from src.schemas.recipe_dto import SearchRequest                     # noqa: E402
from src.services.claude_service import ClaudeProvider               # noqa: E402
from src.services.copilot_service import CopilotService, ProviderConfig  # noqa: E402
from src.services.gemini_service import GeminiProvider               # noqa: E402
from src.services.openrouter_service import OpenRouterProvider       # noqa: E402
from src.services.recipe_service import RecipeService                # noqa: E402

QUERIES = ROOT / "data" / "recipe_rag" / "eval" / "recipe_queries_v1.json"
OUT = ROOT / "data" / "recipe_rag" / "review" / "copilot_eval_{provider}.json"


def make_provider(name, settings):
    if name == "gemini":
        return GeminiProvider(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
    if name == "claude":
        return ClaudeProvider(settings.anthropic_api_key.get_secret_value(), settings.claude_model)
    return OpenRouterProvider(settings.openrouter_api_key.get_secret_value(), settings.openrouter_model)


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))] if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["gemini", "claude", "openrouter"], required=True)
    parser.add_argument("--limit", type=int, default=0, help="chỉ chạy N câu 'found' đầu tiên (0 = tất cả)")
    args = parser.parse_args()

    settings = get_settings()
    key = {"gemini": settings.gemini_api_key, "claude": settings.anthropic_api_key, "openrouter": settings.openrouter_api_key}[args.provider]
    if not key.get_secret_value():
        raise SystemExit(f"Thiếu khóa cho {args.provider} trong .env")

    recipes = RecipeService(settings, Embedder(settings.embedding_model))
    provider = make_provider(args.provider, settings)
    records = []
    service = CopilotService(recipes, {args.provider: provider}, settings, config_source=lambda: [ProviderConfig(args.provider, True, 1)],
                             recorder=records.append)

    name_tokens = {rid: toks(r["name"]) for rid, r in recipes.recipes.items()}
    ingr_tokens = {rid: [toks(i["ingredient"]) for i in r["ingredients"] if i["kind"] == "core"] for rid, r in recipes.recipes.items()}
    queries = [q for q in json.loads(QUERIES.read_text(encoding="utf-8"))["queries"] if q["expect"] == "found"]
    if args.limit:
        queries = queries[:args.limit]

    rows = []
    for n, q in enumerate(queries, 1):
        rel = {rid for rid in recipes.ids if is_relevant(q["relevant"], name_tokens[rid], ingr_tokens[rid])}
        records.clear()
        t0 = time.perf_counter()
        resp = service.answer(SearchRequest(query=q["query"], top_k=settings.copilot_candidates))
        top1 = resp.data.results[0].recipe.id if resp.data.results else None
        chosen = resp.ai.recipe_id if resp.ai else None
        rows.append({"id": q["id"], "type": q["type"], "query": q["query"], "ai_status": resp.ai_status, "attempts": len(records),
                     "attempt_status": [r.status for r in records], "latency_ms": resp.latency_ms,
                     "tokens_in": sum(r.tokens_in or 0 for r in records), "tokens_out": sum(r.tokens_out or 0 for r in records),
                     "top1_relevant": top1 in rel, "chosen": chosen, "chosen_relevant": (chosen in rel) if chosen else None,
                     "chosen_is_top1": (chosen == top1) if chosen else None,
                     "n_item_notes": len(resp.ai.item_notes) if resp.ai else 0, "n_prep_notes": len(resp.ai.prep_notes) if resp.ai else 0,
                     "follow_up": bool(resp.ai and resp.ai.follow_up_question)})
        print(f"[{n}/{len(queries)}] {q['id']} {resp.ai_status:<17} {resp.latency_ms:>6} ms  {q['query'][:50]}", flush=True)

    ok = [r for r in rows if r["ai_status"] == "ok"]
    with_choice = [r for r in rows if r["chosen"]]
    summary = {
        "provider": args.provider, "model": provider.model, "queries": len(rows),
        "ai_status": dict(Counter(r["ai_status"] for r in rows)),
        "ok_rate": round(len(ok) / len(rows), 3) if rows else None,
        "first_try_ok_rate": round(sum(1 for r in ok if r["attempts"] == 1) / len(rows), 3) if rows else None,
        "latency_ms_p50": pct([r["latency_ms"] for r in rows], 0.5), "latency_ms_p95": pct([r["latency_ms"] for r in rows], 0.95),
        "latency_ms_max": max((r["latency_ms"] for r in rows), default=None),
        "tokens_in_total": sum(r["tokens_in"] for r in rows), "tokens_out_total": sum(r["tokens_out"] for r in rows),
        "tokens_in_mean": round(statistics.mean(r["tokens_in"] for r in rows)) if rows else None,
        "tokens_out_mean": round(statistics.mean(r["tokens_out"] for r in rows)) if rows else None,
        "top1_relevant_rate": round(sum(r["top1_relevant"] for r in rows) / len(rows), 3) if rows else None,
        "ai_chosen_relevant_rate": round(sum(r["chosen_relevant"] for r in with_choice) / len(with_choice), 3) if with_choice else None,
        "ai_chose_other_than_top1": sum(1 for r in with_choice if not r["chosen_is_top1"]),
        "ai_fixed_wrong_top1": sum(1 for r in with_choice if not r["top1_relevant"] and r["chosen_relevant"]),
        "ai_broke_right_top1": sum(1 for r in with_choice if r["top1_relevant"] and not r["chosen_relevant"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    out = Path(str(OUT).format(provider=args.provider))
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("đã ghi", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
