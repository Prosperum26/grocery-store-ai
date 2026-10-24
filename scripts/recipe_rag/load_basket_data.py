"""Nạp catalog và giỏ hàng dựng sẵn vào ai_db (bảng catalog_product, recipe_basket) cho ai-service.

Chạy từ thư mục grocery-store-ai (sau load_recipes.py, và sau khi áp db/migrations/002_*.sql):
    .venv\\Scripts\\python scripts\\recipe_rag\\load_basket_data.py
    .venv\\Scripts\\python scripts\\recipe_rag\\load_basket_data.py --dry-run     # làm hết rồi hoàn tác

Đầu vào : data/recipe_rag/final/catalog_v2.json         2.129 sản phẩm (catalog_id khóa cứng)
          data/recipe_rag/final/recipes_matched_v2.json  1.061 món, mỗi dòng nguyên liệu kèm sản phẩm đã ghép
Chạy lại an toàn: ghi đè theo khóa (catalog_id, recipe_id), không nhân đôi. Món có trong file mà chưa có trong
bảng `recipe` thì dừng (phải chạy load_recipes.py trước).
"""
import argparse
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from ai_db import connect

ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "data" / "recipe_rag" / "final"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="làm hết nhưng hoàn tác, không lưu gì")
    args = parser.parse_args()

    catalog = json.loads((FINAL / "catalog_v2.json").read_text(encoding="utf-8"))
    recipes = json.loads((FINAL / "recipes_matched_v2.json").read_text(encoding="utf-8"))
    ids = [c["catalog_id"] for c in catalog]
    if len(set(ids)) != len(ids):
        raise SystemExit("catalog_id trùng trong catalog_v2.json, dừng lại")

    with connect() as conn:                            # thoát khối `with` bình thường thì COMMIT, có lỗi thì ROLLBACK
        known = {r[0] for r in conn.execute("select id from recipe").fetchall()}
        missing = [r["id"] for r in recipes if r["id"] not in known]
        if missing:
            raise SystemExit(f"{len(missing)} món chưa có trong bảng recipe (chạy load_recipes.py trước), ví dụ {missing[:3]}")

        with conn.cursor() as cur:
            cur.executemany(
                """insert into catalog_product (catalog_id, name, category, unit, pack_size, pack_unit, needs_review, status)
                   values (%s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (catalog_id) do update set name = excluded.name, category = excluded.category, unit = excluded.unit,
                       pack_size = excluded.pack_size, pack_unit = excluded.pack_unit, needs_review = excluded.needs_review,
                       status = excluded.status""",
                [(c["catalog_id"], c["name"], c["category"], c["unit"], c["pack_size"], c["pack_unit"], c["needs_review"], c["status"])
                 for c in catalog])
            cur.executemany(
                """insert into recipe_basket (recipe_id, family, in_target_set, complete, ingredients)
                   values (%s, %s, %s, %s, %s)
                   on conflict (recipe_id) do update set family = excluded.family, in_target_set = excluded.in_target_set,
                       complete = excluded.complete, ingredients = excluded.ingredients, loaded_at = now()""",
                [(r["id"], r["family"], r["in_target_set"], r["complete"], Jsonb(r["ingredients"])) for r in recipes])

        n_cat = conn.execute("select count(*) from catalog_product").fetchone()[0]
        n_bas = conn.execute("select count(*), count(*) filter (where complete) from recipe_basket").fetchone()
        print(f"catalog_product: {n_cat} dòng | recipe_basket: {n_bas[0]} món, {n_bas[1]} món đủ nguyên liệu chính")
        if args.dry_run:
            conn.rollback()
            print("--dry-run: đã hoàn tác, chưa lưu gì")


if __name__ == "__main__":
    main()
