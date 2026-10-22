"""Thử tìm công thức bằng câu hỏi tự nhiên (sau load_recipes.py và embed_recipes.py).

Chạy từ thư mục grocery-store-ai:
    .venv\\Scripts\\python scripts\\search_recipes.py "canh chua cá lóc"
    .venv\\Scripts\\python scripts\\search_recipes.py "món nướng cho 4 người"
    .venv\\Scripts\\python scripts\\search_recipes.py "canh chua ca loc" --mode ingredient -k 10

--mode card        (mặc định) so câu hỏi với thẻ món
--mode ingredient  so câu hỏi với từng nguyên liệu; món nào có nguyên liệu khớp nhất thì đứng trên
--target-only      chỉ tìm trong 100 món mục tiêu (những món đã có giỏ hàng, in_target_set = true)
Điểm `sim` là độ giống cosine (1 = giống hệt). Chưa có ngưỡng "không tìm thấy": hãy tự nhìn xem
điểm thấp bao nhiêu thì kết quả bắt đầu sai, đó là dữ liệu để chọn ngưỡng sau này.
"""
import argparse
import os
import re
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import torch
from sentence_transformers import SentenceTransformer

from ai_db import connect

MODEL = "BAAI/bge-m3"
SERVINGS_RE = re.compile(r"\b(?:cho\s+)?(\d+)\s*(?:người|nguoi)\b", re.IGNORECASE)


def split_servings(query):
    """'món nướng cho 4 người' -> ('món nướng', 4). Số người dùng để tính khẩu phần, không phải tên món."""
    m = SERVINGS_RE.search(query)
    if not m:
        return query.strip(), None
    return (query[:m.start()] + " " + query[m.end():]).strip(" ,."), int(m.group(1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--mode", choices=["card", "ingredient"], default="card")
    parser.add_argument("-k", type=int, default=5, help="số kết quả")
    parser.add_argument("--target-only", action="store_true", help="chỉ tìm trong 100 món đã có giỏ hàng")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    text, servings = split_servings(args.query)
    model = SentenceTransformer(MODEL, device=args.device)
    if args.device == "cuda":
        model.half()
    start = time.time()
    q = model.encode([text], normalize_embeddings=True)[0]
    print(f"câu hỏi: '{text}'" + (f" | khẩu phần yêu cầu: {servings} người" if servings else "") + f" | embed {1000 * (time.time() - start):.0f} ms")

    only = "and r.in_target_set" if args.target_only else ""   # điều kiện cố định trong câu SQL, không lấy từ người dùng
    with connect() as conn:
        if args.mode == "card":
            rows = conn.execute(
                """select r.name, r.id, r.in_target_set, r.servings, 1 - (e.embedding <=> %s) as sim, null
                   from recipe_embedding e join recipe r on r.id = e.recipe_id
                   where e.chunk_type = 'card' """ + only + """ order by e.embedding <=> %s limit %s""", (q, q, args.k)).fetchall()
        else:
            # lấy 300 nguyên liệu giống nhất, rồi gộp theo món (điểm món = điểm nguyên liệu tốt nhất)
            rows = conn.execute(
                """with hits as (
                       select recipe_id, content, 1 - (embedding <=> %s) as sim
                       from recipe_embedding where chunk_type = 'ingredient'
                       order by embedding <=> %s limit 300)
                   select r.name, r.id, r.in_target_set, r.servings, max(h.sim) as sim,
                          string_agg(distinct h.content, ', ') as matched
                   from hits h join recipe r on r.id = h.recipe_id
                   where true """ + only + """
                   group by r.name, r.id, r.in_target_set, r.servings
                   order by sim desc limit %s""", (q, q, args.k)).fetchall()

    if not rows:
        # Không nên xảy ra. Nếu gặp: kiểm tra đã embed chưa (embed_recipes.py) và chỉ mục HNSW từng phần (db/migrations).
        print("KHÔNG CÓ KẾT QUẢ nào, đây là lỗi dữ liệu hoặc chỉ mục chứ không phải 'không tìm thấy món'.")
    for rank, (name, rid, target, serv, sim, matched) in enumerate(rows, start=1):
        extra = f" | khớp: {matched}" if matched else ""
        print(f"{rank}. {sim:.3f}  {name}  [{rid}]{' ★100 món' if target else ''} | {serv or '?'} người{extra}")


if __name__ == "__main__":
    main()
