"""Thử luồng RAG đầu-cuối: câu hỏi -> món -> giỏ hàng, và đo độ khớp nguyên liệu <-> sản phẩm catalog.

Chạy từ thư mục grocery-store-ai (cần ai_db đang chạy, đã load_recipes + embed_recipes, và data/final/*_v2.json):
    .venv\\Scripts\\python scripts\\test_rag_basket.py                        # chạy bộ câu hỏi thử + đo toàn bộ giỏ hàng
    .venv\\Scripts\\python scripts\\test_rag_basket.py "gà kho gừng cho 4 người"   # thử 1 câu, in giỏ hàng chi tiết

Ba phần:
  A. TÌM MÓN: mỗi câu hỏi có từ khóa món mong đợi (không dấu, mọi từ khóa phải có trong tên món).
     Đếm top-1 đúng và top-5 có món đúng (Recall@5). Chỉ tìm trong các món đã có giỏ hàng (recipes_v2.json).
  B. GIỎ HÀNG: với món top-1, in từng nguyên liệu -> sản phẩm catalog mặc định, kèm độ giống bge-m3 và cách ghép.
  C. ĐỘ KHỚP TOÀN BỘ: mọi dòng giỏ hàng của mọi món trong recipes_v2.json: tên nguyên liệu vs tên sản phẩm.
     `chua_tu` = mọi từ của tên nguyên liệu đều có trong tên sản phẩm; `sim` = cosine bge-m3.
Ghi data/review/rag_test_results.json để đưa vào notebook.
Điểm sim của tên sản phẩm bị kéo thấp vì tên có thương hiệu, quy cách (Bột chiên xù Miwon 200g): đọc theo phân bố, không theo một ngưỡng cứng.
"""
import json
import os
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from ai_db import connect
from search_recipes import MODEL, split_servings

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "data" / "final"
OUT = ROOT / "data" / "review" / "rag_test_results.json"

# (câu hỏi, các từ khóa món mong đợi). Từ khóa viết không dấu thường; mọi từ khóa phải có trong tên món (so không dấu).
QUERIES = [
    ("canh chua cá lóc", ["canh chua", "ca loc"]),
    ("gà kho gừng", ["ga", "kho", "gung"]),
    ("sườn xào chua ngọt", ["suon", "chua ngot"]),
    ("bò xào hành tây", ["bo", "xao", "hanh tay"]),
    ("cá kho tộ", ["ca", "kho"]),
    ("lẩu thái hải sản", ["lau", "thai"]),
    ("bún riêu cua", ["bun rieu"]),
    ("thịt kho trứng", ["thit kho"]),
    ("bánh xèo", ["banh xeo"]),
    ("chả giò", ["cha gio"]),
    ("canh bí đao nấu tôm", ["bi dao"]),
    ("rau muống xào tỏi", ["rau muong"]),
    ("đậu hũ sốt cà chua", ["dau hu"]),
    ("cơm chiên dương châu", ["com chien"]),
    ("mực xào sa tế", ["muc", "sa te"]),
    ("tôm rang me", ["rang me"]),
    ("gà nướng mật ong", ["ga", "nuong"]),
    ("mì ý sốt bò bằm", ["mi y"]),
    ("cà ri gà", ["ca ri"]),
    ("trứng chiên", ["trung"]),
    ("canh khổ qua nhồi thịt", ["kho qua"]),
    ("gỏi cuốn tôm thịt", ["goi cuon"]),
    ("ga kho gung cho 4 nguoi", ["ga", "kho", "gung"]),            # không dấu + khẩu phần
    ("món nướng cho 4 người", ["nuong"]),                          # câu hỏi chung
    ("cháo gà", ["chao"]),
    ("lươn xào sả ớt", ["luon"]),                                  # nguyên liệu hiếm vừa thêm vào catalog
    ("canh chua bồn bồn", ["bon bon"]),
    ("điện thoại iphone 15", None),                                # ngoài chủ đề: mong đợi điểm thấp
]


def norm(text):
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokens(text):
    return [t for t in norm(text).replace(",", " ").replace("(", " ").replace(")", " ").split() if t]


def main():
    one = sys.argv[1] if len(sys.argv) > 1 else None
    recipes = {r["id"]: r for r in json.loads((FINAL / "recipes_v2.json").read_text(encoding="utf-8"))}
    catalog = {c["catalog_id"]: c for c in json.loads((FINAL / "catalog_v2.json").read_text(encoding="utf-8"))}
    via_of = {e["ingredient"]: e["via"] for e in json.loads((FINAL / "ingredient_to_catalog_v2.json").read_text(encoding="utf-8"))}
    ids = list(recipes)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL, device=device)
    if device == "cuda":
        model.half()

    # ---------- C. độ khớp nguyên liệu <-> sản phẩm (tính trước để dùng lại ở phần B) ----------
    pairs = {}                                                    # (ingredient, catalog_id) -> dict
    for r in recipes.values():
        for b in r["basket"]:
            if b["default_catalog_id"]:
                pairs.setdefault((b["ingredient"], b["default_catalog_id"]), {"kind": b["kind"]})
    ing_names = sorted({i for i, _ in pairs})
    prod_ids = sorted({c for _, c in pairs})
    t0 = time.time()
    ing_vec = dict(zip(ing_names, model.encode(ing_names, batch_size=64, normalize_embeddings=True)))
    prod_vec = dict(zip(prod_ids, model.encode([catalog[c]["name"] for c in prod_ids], batch_size=64, normalize_embeddings=True)))
    for (ing, cid), d in pairs.items():
        d["sim"] = float(ing_vec[ing] @ prod_vec[cid])
        d["contains"] = set(tokens(ing)) <= set(tokens(catalog[cid]["name"]))
        d["via"] = via_of.get(ing)
    print(f"đã embed {len(ing_names)} tên nguyên liệu + {len(prod_ids)} tên sản phẩm trong {time.time() - t0:.0f}s")

    def show_basket(rid, indent="   "):
        r = recipes[rid]
        for b in r["basket"]:
            if not b["default_catalog_id"]:
                print(f"{indent}{b['kind']:5} {b['ingredient']:30} -> (chưa có)")
                continue
            d = pairs[(b["ingredient"], b["default_catalog_id"])]
            flag = "" if d["contains"] or d["sim"] >= 0.6 else "  <-- kiểm"
            print(f"{indent}{b['kind']:5} {b['ingredient'][:28]:28} -> {catalog[b['default_catalog_id']]['name'][:46]:46} "
                  f"x{b['packs']} | sim {d['sim']:.2f} {'chứa' if d['contains'] else '    '} | {d['via']}{flag}")

    def search(query, k=5):
        text, servings = split_servings(query)
        q = model.encode([text], normalize_embeddings=True)[0]
        with connect() as conn:
            rows = conn.execute(
                """select r.id, r.name, 1 - (e.embedding <=> %s) as sim from recipe_embedding e join recipe r on r.id = e.recipe_id
                   where e.chunk_type = 'card' and r.id = any(%s) order by e.embedding <=> %s limit %s""", (q, ids, q, k)).fetchall()
        return text, servings, rows

    if one:
        text, servings, rows = search(one)
        print(f"\ncâu hỏi: '{text}'" + (f" | {servings} người" if servings else ""))
        for rank, (rid, name, sim) in enumerate(rows, 1):
            print(f"  {rank}. {sim:.3f}  {name}  [{rid}]")
        print(f"\nGiỏ hàng của món #1 ({recipes[rows[0][0]]['servings']} người, mua nguyên gói):")
        show_basket(rows[0][0])
        return

    # ---------- A + B ----------
    results, top1_ok, top5_ok, scored = [], 0, 0, 0
    for query, expect in QUERIES:
        text, servings, rows = search(query)
        hit_rank = None
        if expect:
            for rank, (rid, name, sim) in enumerate(rows, 1):
                if all(k in norm(name) for k in expect):
                    hit_rank = rank
                    break
            scored += 1
            top1_ok += hit_rank == 1
            top5_ok += hit_rank is not None
        print(f"\n[{'ĐÚNG' if hit_rank == 1 else f'top{hit_rank}' if hit_rank else ('---' if not expect else 'SAI')}] '{query}'"
              f"{f' ({servings} người)' if servings else ''}")
        for rank, (rid, name, sim) in enumerate(rows[:3], 1):
            print(f"    {rank}. {sim:.3f} {name[:70]}")
        entry = {"query": query, "expect": expect, "hit_rank": hit_rank, "top": [{"id": rid, "name": n, "sim": round(float(s), 3)} for rid, n, s in rows]}
        if rows and (hit_rank == 1 or not expect):
            rid = rows[0][0]
            if expect:
                show_basket(rid, "      ")
            entry["basket"] = [{"ingredient": b["ingredient"], "kind": b["kind"], "packs": b["packs"],
                                "product": catalog[b["default_catalog_id"]]["name"] if b["default_catalog_id"] else None,
                                "sim": round(pairs[(b["ingredient"], b["default_catalog_id"])]["sim"], 3) if b["default_catalog_id"] else None,
                                "contains": pairs[(b["ingredient"], b["default_catalog_id"])]["contains"] if b["default_catalog_id"] else None,
                                "via": via_of.get(b["ingredient"])} for b in recipes[rid]["basket"]]
        results.append(entry)
    off = [e for e in results if not e["expect"]]
    print(f"\n=== TÌM MÓN: top-1 đúng {top1_ok}/{scored} | có trong top-5 (Recall@5) {top5_ok}/{scored}")
    print("    điểm top-1 của câu ngoài chủ đề:", [e["top"][0]["sim"] for e in off])
    ok_scores = [e["top"][0]["sim"] for e in results if e["expect"] and e["hit_rank"] == 1]
    bad_scores = [e["top"][0]["sim"] for e in results if e["expect"] and e["hit_rank"] != 1]
    print(f"    điểm top-1 khi đúng: min {min(ok_scores):.3f} / trung vị {np.median(ok_scores):.3f} | khi sai: {sorted(bad_scores)}")

    # ---------- C ----------
    vals = np.array([d["sim"] for d in pairs.values()])
    contains = np.mean([d["contains"] for d in pairs.values()])
    by_via = defaultdict(list)
    for d in pairs.values():
        by_via[d["via"]].append(d)
    print(f"\n=== ĐỘ KHỚP NGUYÊN LIỆU <-> SẢN PHẨM ({len(pairs)} cặp khác nhau, từ {sum(len(r['basket']) for r in recipes.values())} dòng giỏ hàng)")
    print(f"    sim: trung bình {vals.mean():.3f} | trung vị {np.median(vals):.3f} | p10 {np.percentile(vals, 10):.3f} | p90 {np.percentile(vals, 90):.3f}")
    print(f"    tên sản phẩm chứa đủ từ của nguyên liệu: {100 * contains:.0f}% cặp")
    print(f"    sim < 0.5: {int((vals < 0.5).sum())} cặp | sim < 0.6 và không chứa đủ từ: {sum(1 for d in pairs.values() if d['sim'] < 0.6 and not d['contains'])} cặp")
    table = []
    for via, ds in sorted(by_via.items(), key=lambda x: -len(x[1])):
        row = {"via": via, "cap": len(ds), "sim_tb": round(float(np.mean([d['sim'] for d in ds])), 3),
               "chua_tu_pct": round(100 * float(np.mean([d['contains'] for d in ds]))), "nghi_sai": sum(1 for d in ds if d['sim'] < 0.6 and not d['contains'])}
        table.append(row)
        print(f"    {str(via):26} {row['cap']:4} cặp | sim tb {row['sim_tb']:.3f} | chứa từ {row['chua_tu_pct']:3}% | nghi sai {row['nghi_sai']}")
    worst = sorted(((d["sim"], ing, cid) for (ing, cid), d in pairs.items() if not d["contains"]))[:25]
    print("    25 cặp khác nhau nhất (không chứa từ, sim thấp):")
    for sim, ing, cid in worst:
        print(f"      {sim:.2f} {ing[:30]:30} -> {catalog[cid]['name'][:50]}  [{via_of.get(ing)}]")

    OUT.write_text(json.dumps({
        "queries": results, "find_dish": {"top1": top1_ok, "recall5": top5_ok, "scored": scored},
        "ingredient_match": {"pairs": len(pairs), "sim_mean": round(float(vals.mean()), 3), "sim_median": round(float(np.median(vals)), 3),
                             "sim_p10": round(float(np.percentile(vals, 10)), 3), "contains_pct": round(100 * float(contains)),
                             "by_via": table,
                             "worst": [{"sim": round(s, 3), "ingredient": i, "product": catalog[c]["name"], "via": via_of.get(i)} for s, i, c in worst]},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
