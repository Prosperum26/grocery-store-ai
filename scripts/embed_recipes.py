"""Embed công thức bằng bge-m3 (1024 chiều) rồi lưu vào recipe_embedding trong ai_db.

Chạy từ thư mục grocery-store-ai (sau load_recipes.py):
    .venv\\Scripts\\python scripts\\embed_recipes.py                      # cả 2 loại chunk, tự dùng GPU nếu có
    .venv\\Scripts\\python scripts\\embed_recipes.py --chunks card        # chỉ thẻ món (nhanh nhất)
    .venv\\Scripts\\python scripts\\embed_recipes.py --device cpu         # ép dùng CPU (chậm hơn nhiều)

Hai loại chunk (xem db/init/02_schema.sql):
  card        1 chunk mỗi món: tên (kèm bản không dấu), mô tả, các nguyên liệu chính
  ingredient  1 chunk mỗi dòng nguyên liệu CHÍNH (role = main): tên nguyên liệu (kèm dạng phi/xay/rang)
Chạy lại an toàn: dùng upsert nên không bị nhân đôi, chỉ ghi đè.
Cần model BAAI/bge-m3 đã nằm trong cache Hugging Face (đã tải khi chạy build_alias_candidates.py).
"""
import argparse
import os
import time
import unicodedata

os.environ.setdefault("HF_HUB_OFFLINE", "1")     # model đã có trong cache, không cần hỏi mạng (tránh chờ khi mạng yếu)

import torch
from sentence_transformers import SentenceTransformer

from ai_db import connect

MODEL = "BAAI/bge-m3"
INSERT_BATCH = 1000


def strip_accents(text):
    """'Canh chua cá lóc' -> 'Canh chua ca loc', vì khách hay gõ không dấu."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def card_text(name, description, main_ingredients):
    """Nội dung thẻ món. Ngắn và đúng trọng tâm: khách hỏi bằng tên món hoặc nguyên liệu, không hỏi cách làm."""
    ingredients = ", ".join(dict.fromkeys(main_ingredients))[:300]       # bỏ trùng, giữ thứ tự, cắt 300 ký tự
    return f"{name} ({strip_accents(name)}). {description or ''} Nguyên liệu: {ingredients}".strip()


def encode(model, texts, batch_size):
    return model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)


def upsert(conn, sql, rows):
    with conn.cursor() as cur:
        for start in range(0, len(rows), INSERT_BATCH):
            cur.executemany(sql, rows[start:start + INSERT_BATCH])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", choices=["card", "ingredient", "both"], default="both")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    start = time.time()
    model = SentenceTransformer(MODEL, device=args.device)
    if args.device == "cuda":
        model.half()                                          # fp16: nhanh hơn, ít VRAM, vector gần như không đổi (đã đo)
    print(f"nạp model ({args.device}): {time.time() - start:.1f}s")

    with connect() as conn:
        if conn.execute("select count(*) from recipe").fetchone()[0] == 0:
            raise SystemExit("recipe đang trống. Chạy scripts/load_recipes.py trước.")

        if args.chunks in ("card", "both"):
            rows = conn.execute(
                """select r.id, r.name, r.description,
                          coalesce(array_agg(i.name order by i.position) filter (where i.role = 'main'), '{}')
                   from recipe r left join recipe_ingredient i on i.recipe_id = r.id
                   group by r.id, r.name, r.description order by r.id""").fetchall()
            texts = [card_text(name, description, main) for _, name, description, main in rows]
            t = time.time()
            vectors = encode(model, texts, 32)               # thẻ dài hơn nên dùng lô nhỏ hơn
            print(f"embed {len(texts)} thẻ món: {time.time() - t:.1f}s")
            upsert(conn, """insert into recipe_embedding (recipe_id, chunk_type, content, embedding, model)
                            values (%s, 'card', %s, %s, %s)
                            on conflict (recipe_id) where chunk_type = 'card'
                            do update set content = excluded.content, embedding = excluded.embedding,
                                          model = excluded.model, created_at = now()""",
                   [(rid, text, vec, MODEL) for (rid, *_), text, vec in zip(rows, texts, vectors)])

        if args.chunks in ("ingredient", "both"):
            rows = conn.execute("select id, recipe_id, name, form from recipe_ingredient where role = 'main' order by id").fetchall()
            content = [f"{name} {form}" if form else name for _, _, name, form in rows]
            distinct = sorted(set(content))                  # cùng một chuỗi xuất hiện ở nhiều món: chỉ embed một lần
            t = time.time()
            vec_of = dict(zip(distinct, encode(model, distinct, args.batch_size)))
            print(f"embed {len(distinct)} chuỗi nguyên liệu khác nhau (cho {len(rows)} dòng): {time.time() - t:.1f}s")
            upsert(conn, """insert into recipe_embedding (recipe_id, ingredient_id, chunk_type, content, embedding, model)
                            values (%s, %s, 'ingredient', %s, %s, %s)
                            on conflict (ingredient_id) where chunk_type = 'ingredient'
                            do update set content = excluded.content, embedding = excluded.embedding,
                                          model = excluded.model, created_at = now()""",
                   [(rid, iid, c, vec_of[c], MODEL) for (iid, rid, _, _), c in zip(rows, content)])

        stats = conn.execute("select chunk_type, count(*) from recipe_embedding group by 1 order by 1").fetchall()
        print("recipe_embedding hiện có:", dict(stats), f"| tổng thời gian {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
