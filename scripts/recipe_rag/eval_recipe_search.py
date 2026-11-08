"""Đo chất lượng tìm món: Recall@5 chính thức, so với ILIKE, và chọn ngưỡng "không tìm thấy".

Chạy từ thư mục grocery-store-ai (cần ai_db đang chạy, đã load_recipes + embed_recipes, và data/recipe_rag/final/recipes_v2.json):
    .venv\\Scripts\\python scripts\\recipe_rag\\eval_recipe_search.py

Đầu vào : data/recipe_rag/eval/recipe_queries_v1.json   108 câu hỏi có nhãn (7 loại)
          data/recipe_rag/final/recipes_v2.json         1.061 món có giỏ hàng (chỉ tìm trong tập này)
Đầu ra  : data/recipe_rag/review/recipe_search_eval_v1.json

Bốn cách tìm được so sánh trên cùng bộ câu hỏi:
  ilike_cau    SQL: tên món ILIKE '%nguyên câu hỏi%'                     (baseline H5 thô nhất)
  ilike_tu     SQL: mọi từ của câu hỏi đều ILIKE trong tên món (có dấu)   (baseline thông dụng)
  ilike_chuan  Python: bỏ dấu, bỏ từ thừa (món, với, cho...), mọi từ có trong tên món (baseline mạnh nhất có thể)
  bge_m3       tìm theo thẻ món bằng embedding (cosine), lấy 10 món đầu
  hybrid       món khớp từ khóa chuẩn hóa (ilike_chuan) đứng trước, rồi tới món của bge_m3. Chấp nhận kết quả nếu
               có món khớp từ khóa HOẶC sim top-1 >= ngưỡng (câu không dấu/gõ sai vẫn qua được nhờ nhánh từ khóa)
ILIKE xếp hạng theo tên ngắn trước (không có điểm số). Chỉ 'found' mới tính Recall; 'reject' dùng để chọn ngưỡng.
Ngưỡng: chọn trên nửa dev (câu số lẻ trong mỗi loại), báo trên nửa test (câu số chẵn) để khỏi tự chấm tự khen.
"""
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from ai_db import connect
from search_recipes import MODEL, split_servings

ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "data" / "recipe_rag" / "eval" / "recipe_queries_v1.json"
OUT = ROOT / "data" / "recipe_rag" / "review" / "recipe_search_eval_v1.json"
K = 10
STOPWORDS = {"mon", "voi", "co", "va", "cho", "nguoi", "nau", "gi", "tu", "cach", "lam", "de", "mot", "nhung", "hay"}
GRID = [round(x, 2) for x in np.arange(0.30, 0.76, 0.02)]


def norm(text):
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def toks(text):
    return re.findall(r"[a-z0-9]+", norm(text))


def has_phrase(tokens, phrase):
    p = toks(phrase)
    return any(tokens[i:i + len(p)] == p for i in range(len(tokens) - len(p) + 1))


def is_relevant(rule, name_tokens, ingredient_tokens):
    if "name_all" in rule:
        return all(has_phrase(name_tokens, k) for k in rule["name_all"])
    if "name_any" in rule:
        return any(has_phrase(name_tokens, k) for k in rule["name_any"])
    return all(any(has_phrase(t, k) for t in ingredient_tokens) for k in rule["ingr_all"])


def main():
    data = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    recipes = {r["id"]: r for r in json.loads((ROOT / "data" / "recipe_rag" / "final" / "recipes_v2.json").read_text(encoding="utf-8"))}
    ids = list(recipes)
    name_tokens = {rid: toks(r["name"]) for rid, r in recipes.items()}
    ingr_tokens = {rid: [toks(b["ingredient"]) for b in r["basket"] if b["kind"] == "core"] for rid, r in recipes.items()}

    # tập món đúng của mỗi câu hỏi; kiểm tra nhãn có ý nghĩa
    for q in data:
        if q["relevant"]:
            q["rel_ids"] = {rid for rid in ids if is_relevant(q["relevant"], name_tokens[rid], ingr_tokens[rid])}
            if not q["rel_ids"]:
                raise SystemExit(f"{q['id']} '{q['query']}': không món nào khớp nhãn, sửa nhãn trước khi đo")
        else:
            q["rel_ids"] = set()
    for q in data:                                              # 'khong_co_mon' phải thật sự không có món
        if q["type"] == "khong_co_mon":
            words = [w for w in toks(q["query"]) if w not in STOPWORDS]
            exact = [recipes[rid]["name"] for rid in ids if all(w in name_tokens[rid] for w in words)]
            q["exist_check"] = exact[:3]
            if exact:
                print(f"CẢNH BÁO {q['id']} '{q['query']}' có món khớp từng từ trong tên: {exact[:3]} (xem lại nhãn)")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL, device=device)
    if device == "cuda":
        model.half()

    def ilike_sql(conn, words, mode):
        if mode == "cau":
            cond, params = "r.name ilike %s", [f"%{words}%"]
        else:
            ws = words.split()
            cond, params = " and ".join(["r.name ilike %s"] * len(ws)), [f"%{w}%" for w in ws]
        rows = conn.execute(f"select r.id from recipe r where r.id = any(%s) and {cond} order by length(r.name), r.id limit {K}",
                            [ids, *params]).fetchall()
        return [r[0] for r in rows]

    def ilike_chuan(text):
        words = [w for w in toks(text) if w not in STOPWORDS]
        if not words:
            return []
        hit = [rid for rid in ids if all(w in name_tokens[rid] for w in words)]
        return sorted(hit, key=lambda rid: (len(recipes[rid]["name"]), rid))[:K]

    results = []
    with connect() as conn:
        for q in data:
            text, servings = split_servings(q["query"])
            vec = model.encode([text], normalize_embeddings=True)[0]
            rows = conn.execute(
                """select r.id, 1 - (e.embedding <=> %s) from recipe_embedding e join recipe r on r.id = e.recipe_id
                   where e.chunk_type = 'card' and r.id = any(%s) order by e.embedding <=> %s limit %s""", (vec, ids, vec, K)).fetchall()
            methods = {
                "ilike_cau": ilike_sql(conn, text, "cau"), "ilike_tu": ilike_sql(conn, text, "tu"), "ilike_chuan": ilike_chuan(text),
                "bge_m3": [r[0] for r in rows],
            }
            lex = methods["ilike_chuan"]
            methods["hybrid"] = (lex + [rid for rid in methods["bge_m3"] if rid not in lex])[:K]
            results.append({"id": q["id"], "type": q["type"], "query": q["query"], "expect": q["expect"], "n_rel": len(q["rel_ids"]),
                            "top1_sim": float(rows[0][1]), "lex_hit": bool(lex), "top_sims": [round(float(r[1]), 3) for r in rows[:5]],
                            "top_names": [recipes[r[0]]["name"] for r in rows[:3]], "ranks": {}, "rel": q["rel_ids"], "methods": methods})
            for m, lst in methods.items():
                rank = next((i for i, rid in enumerate(lst, 1) if rid in q["rel_ids"]), None) if q["expect"] == "found" else None
                results[-1]["ranks"][m] = rank

    # ---------- Recall ----------
    found = [r for r in results if r["expect"] == "found"]
    summary = {}
    print(f"{len(results)} câu hỏi: {len(found)} có món đúng, {len(results) - len(found)} nên từ chối")
    print("\n=== RECALL (tính trên câu có món đúng)")
    MS = ["ilike_cau", "ilike_tu", "ilike_chuan", "bge_m3", "hybrid"]
    print(f"{'':16}" + "".join(f"{m:>14}" for m in MS))
    groups = [("TẤT CẢ", found)] + [(t, [r for r in found if r["type"] == t]) for t in dict.fromkeys(r["type"] for r in found)]
    for label, rs in groups:
        line = {}
        for m in MS:
            r1 = sum(1 for r in rs if r["ranks"][m] == 1) / len(rs)
            r5 = sum(1 for r in rs if r["ranks"][m] is not None and r["ranks"][m] <= 5) / len(rs)
            mrr = float(np.mean([1 / r["ranks"][m] if r["ranks"][m] else 0 for r in rs]))
            line[m] = {"recall1": round(r1, 3), "recall5": round(r5, 3), "mrr": round(mrr, 3)}
        summary[label] = {"n": len(rs), **line}
        print(f"{label:16}" + "".join(f"  @1 {line[m]['recall1']:.2f} @5 {line[m]['recall5']:.2f}"[:14].rjust(14) if False else f"{line[m]['recall1']:.2f}/{line[m]['recall5']:.2f}".rjust(14)
                                      for m in MS) + f"   (n={len(rs)}, Recall@1/Recall@5)")
    # câu bge-m3 trượt top-5
    miss = [r for r in found if r["ranks"]["bge_m3"] is None or r["ranks"]["bge_m3"] > 5]
    print(f"\nbge-m3 trượt top-5: {len(miss)} câu")
    for r in miss:
        print(f"  {r['id']} [{r['type']}] '{r['query']}' (có {r['n_rel']} món đúng) -> {r['top_names'][:2]} sim {r['top_sims'][0]:.2f}")

    # ---------- ngưỡng ----------
    for r in results:
        pos = [x for x in results if x["type"] == r["type"]].index(r)
        r["split"] = "dev" if pos % 2 == 0 else "test"

    def at(t, rs, method="bge_m3"):
        def accept(r):
            return r["top1_sim"] >= t or (method == "hybrid" and r["lex_hit"])
        fnd = [r for r in rs if r["expect"] == "found"]
        rej = [r for r in rs if r["expect"] == "reject"]
        served_ok = sum(1 for r in fnd if accept(r) and r["ranks"][method] is not None and r["ranks"][method] <= 5) / max(1, len(fnd))
        wrongly_rejected = sum(1 for r in fnd if not accept(r)) / max(1, len(fnd))
        rejected = sum(1 for r in rej if not accept(r)) / max(1, len(rej))
        return served_ok, wrongly_rejected, rejected, (served_ok + rejected) / 2

    dev = [r for r in results if r["split"] == "dev"]
    test = [r for r in results if r["split"] == "test"]
    print("\n=== NGƯỠNG 'không tìm thấy' (nhận kết quả nếu sim top-1 >= ngưỡng)")
    print("  ngưỡng | dev: phục vụ đúng / từ chối đúng / cân bằng | test: phục vụ đúng / từ chối đúng / cân bằng")
    curve = []
    for t in GRID:
        d, e = at(t, dev), at(t, test)
        curve.append({"t": t, "dev": [round(x, 3) for x in d], "test": [round(x, 3) for x in e]})
        print(f"   {t:.2f}  |  {d[0]:.2f} / {d[2]:.2f} / {d[3]:.2f}  |  {e[0]:.2f} / {e[2]:.2f} / {e[3]:.2f}")
    best = max(GRID, key=lambda t: (at(t, dev)[3], -t))
    print(f"\nngưỡng chọn trên dev (cân bằng cao nhất): {best:.2f} -> test: phục vụ đúng {at(best, test)[0]:.2f}, từ chối đúng {at(best, test)[2]:.2f}")

    best_h = max(GRID, key=lambda t: (at(t, dev, "hybrid")[3], -t))
    print(f"\n--- hybrid (từ khóa HOẶC sim >= ngưỡng): ngưỡng chọn trên dev {best_h:.2f} -> test: phục vụ đúng {at(best_h, test, 'hybrid')[0]:.2f}, "
          f"từ chối đúng {at(best_h, test, 'hybrid')[2]:.2f}")
    for t in (0.50, 0.56, 0.60, 0.62, 0.66):
        a, b = at(t, dev + test, "bge_m3"), at(t, dev + test, "hybrid")
        print(f"   t={t:.2f} toàn bộ: bge_m3 phục vụ đúng {a[0]:.2f}, từ chối đúng {a[2]:.2f} | hybrid phục vụ đúng {b[0]:.2f}, từ chối đúng {b[2]:.2f}")
    lex_false = [r["query"] for r in results if r["expect"] == "reject" and r["lex_hit"]]
    print("   câu nên từ chối mà nhánh từ khóa vẫn tìm ra món:", lex_false)

    by_type = {}
    print("\n=== sim top-1 theo loại câu hỏi")
    for t in dict.fromkeys(r["type"] for r in results):
        s = np.array([r["top1_sim"] for r in results if r["type"] == t])
        by_type[t] = {"n": len(s), "min": round(float(s.min()), 3), "median": round(float(np.median(s)), 3), "max": round(float(s.max()), 3)}
        print(f"  {t:18} n={len(s):3} min {s.min():.2f} | trung vị {np.median(s):.2f} | max {s.max():.2f}")
    hit_sims = [r["top1_sim"] for r in found if r["ranks"]["bge_m3"] == 1]
    miss_sims = [r["top1_sim"] for r in found if r["ranks"]["bge_m3"] != 1]
    print(f"  top-1 ĐÚNG: n={len(hit_sims)} trung vị {np.median(hit_sims):.2f} | top-1 KHÔNG đúng: n={len(miss_sims)} trung vị {np.median(miss_sims):.2f}")

    OUT.write_text(json.dumps({
        "n_queries": len(results), "n_found": len(found), "summary": summary, "threshold_chosen_on_dev": best, "hybrid_threshold_chosen_on_dev": best_h,
        "hybrid_threshold_test": dict(zip(["served_ok", "wrongly_rejected", "rejected_ok", "balanced"], [round(x, 3) for x in at(best_h, test, "hybrid")])),
        "all_data_at": {str(t): {"bge_m3": [round(x, 3) for x in at(t, dev + test, "bge_m3")], "hybrid": [round(x, 3) for x in at(t, dev + test, "hybrid")]} for t in (0.5, 0.56, 0.6, 0.62, 0.66)},
        "lex_false_accept": lex_false,
        "threshold_test": dict(zip(["served_ok", "wrongly_rejected", "rejected_ok", "balanced"], [round(x, 3) for x in at(best, test)])),
        "curve": curve, "sim_by_type": by_type,
        "bge_miss": [{"id": r["id"], "type": r["type"], "query": r["query"], "n_rel": r["n_rel"], "top": r["top_names"][:3], "sim": round(r["top1_sim"], 3)} for r in miss],
        "reject_cases": [{"id": r["id"], "type": r["type"], "query": r["query"], "top1": r["top_names"][0], "sim": round(r["top1_sim"], 3)}
                         for r in results if r["expect"] == "reject"],
        "per_query": [{"id": r["id"], "type": r["type"], "query": r["query"], "expect": r["expect"], "n_rel": r["n_rel"], "split": r["split"],
                       "top1_sim": round(r["top1_sim"], 3), "ranks": r["ranks"]} for r in results],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
