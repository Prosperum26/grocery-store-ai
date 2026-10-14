"""Gợi ý gộp tên đồng nghĩa và gợi ý ghép nguyên liệu -> sản phẩm catalog bằng bge-m3.

Chạy từ thư mục grocery-store-ai (cần: pip install sentence-transformers):
    python scripts/build_alias_candidates.py

Đầu vào : data/processed/recipes_clean.json, data/processed/catalog_clean.json
Đầu ra  : data/processed/alias_candidates.csv     tên hiếm -> tên phổ biến giống nó (để duyệt tay)
          data/processed/catalog_candidates.csv   mỗi nguyên liệu -> top-3 loại hàng trong catalog
Script CHỈ ĐỀ XUẤT. bge-m3 coi "ớt đỏ" và "ớt xanh" rất giống nhau, nên không tự gộp:
người duyệt đánh dấu cột `accept`, rồi chép các dòng đúng vào ALIASES trong build_recipes_clean.py.
"""
import csv
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
MIN_COUNT_ALIAS = 3        # chỉ xét tên xuất hiện >= 3 lần
MIN_COUNT_CATALOG = 5      # chỉ ghép catalog cho tên xuất hiện >= 5 lần
ALIAS_SIM = 0.85           # ngưỡng cosine để đề xuất gộp (chưa tune, xem báo cáo)


def relation(a, b):
    """'variant' nếu tên này là phần mở rộng của tên kia ("ớt" / "ớt chuông"), còn lại 'synonym?'."""
    if a.startswith(b + " ") or b.startswith(a + " "):
        return "variant"
    return "synonym?"


def main():
    recipes = json.loads((PROC / "recipes_clean.json").read_text(encoding="utf-8"))
    catalog = json.loads((PROC / "catalog_clean.json").read_text(encoding="utf-8"))
    counts = Counter(i["name"] for r in recipes for i in r["ingredients"])
    bases = sorted({p["base"] for p in catalog})
    base_category = {}
    for p in catalog:
        base_category.setdefault(p["base"], p["category"])

    texts = sorted(set(counts) | set(bases))
    print(f"embedding {len(texts)} chuỗi bằng BAAI/bge-m3 (CPU)...")
    t0 = time.time()
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    print(f"load model: {time.time() - t0:.1f}s | max_seq_length={model.max_seq_length}")
    t1 = time.time()
    emb = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    dt = time.time() - t1
    print(f"embed: {dt:.1f}s ({dt / len(texts) * 1000:.1f} ms/chuỗi) | vector shape {emb.shape}")
    np.save(PROC / "name_embeddings.npy", emb)  # cache, bị .gitignore chặn
    index = {t: k for k, t in enumerate(texts)}

    # 1) Tên hiếm -> tên phổ biến hơn giống nó nhất.
    names = [n for n, c in counts.items() if c >= MIN_COUNT_ALIAS]
    pool = [n for n in counts if counts[n] >= MIN_COUNT_ALIAS]
    pool_emb = emb[[index[n] for n in pool]]
    rows = []
    for n in names:
        sims = pool_emb @ emb[index[n]]
        for j in np.argsort(-sims)[:4]:
            m = pool[j]
            if m != n and counts[m] > counts[n] and sims[j] >= ALIAS_SIM:
                rows.append([n, counts[n], m, counts[m], f"{sims[j]:.3f}", relation(n, m), ""])
    rows.sort(key=lambda r: (r[5], -float(r[4])))
    with (PROC / "alias_candidates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "count", "merge_into", "target_count", "similarity", "relation", "accept"])
        w.writerows(rows)
    print(f"alias_candidates: {len(rows)} dòng ({sum(r[5] == 'synonym?' for r in rows)} synonym?)")

    # 2) Nguyên liệu -> top-3 loại hàng catalog.
    base_emb = emb[[index[b] for b in bases]]
    rows = []
    for n, c in counts.most_common():
        if c < MIN_COUNT_CATALOG:
            break
        sims = base_emb @ emb[index[n]]
        for rank, j in enumerate(np.argsort(-sims)[:3], 1):
            b = bases[j]
            lexical = "exact" if b == n else "prefix" if b.startswith(n + " ") else ""
            rows.append([n, c, rank, b, base_category[b], f"{sims[j]:.3f}", lexical, ""])
    with (PROC / "catalog_candidates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "count", "rank", "catalog_base", "category", "similarity", "lexical", "accept"])
        w.writerows(rows)
    print(f"catalog_candidates: {len(rows)} dòng cho {len(rows) // 3} nguyên liệu")


if __name__ == "__main__":
    main()
