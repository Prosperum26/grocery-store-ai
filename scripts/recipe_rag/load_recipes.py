"""Nạp công thức và nguyên liệu đã chuẩn hóa vào ai_db (bảng recipe, recipe_ingredient).

Chạy từ thư mục grocery-store-ai:
    .venv\\Scripts\\python scripts\\recipe_rag\\load_recipes.py              # nạp lần đầu (bảng phải đang trống)
    .venv\\Scripts\\python scripts\\recipe_rag\\load_recipes.py --reset      # XÓA SẠCH rồi nạp lại (cả embedding, phải embed lại)
    .venv\\Scripts\\python scripts\\recipe_rag\\load_recipes.py --limit 20 --dry-run   # thử 20 món, không lưu gì

Đầu vào : data/recipe_rag/processed/recipes_clean.json   2.527 công thức (scripts/recipe_rag/build_recipes_clean.py)
          data/recipe_rag/final/recipes_v1.json          100 công thức mục tiêu -> cột in_target_set
Cần ai_db đang chạy (docker compose up -d) và file .env.
"""
import argparse
import ast
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from ai_db import connect

ROOT = Path(__file__).resolve().parents[2]


def to_int(value):
    """'4' -> 4; '0', '', None, chữ lạ -> None (nguồn ghi 0 nghĩa là không rõ khẩu phần)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_list(value):
    """Các trường bước làm trong dữ liệu crawl là chuỗi dạng "['bước 1', 'bước 2']" -> list chuỗi."""
    try:
        items = ast.literal_eval(value) if isinstance(value, str) else value
    except (ValueError, SyntaxError):
        return []
    return [s.strip() for s in items if isinstance(s, str) and s.strip()] if isinstance(items, list) else []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="xóa sạch recipe, recipe_ingredient, recipe_embedding rồi nạp lại")
    parser.add_argument("--limit", type=int, help="chỉ nạp N công thức đầu tiên (để thử)")
    parser.add_argument("--dry-run", action="store_true", help="làm hết nhưng hoàn tác, không lưu gì")
    args = parser.parse_args()

    recipes = json.loads((ROOT / "data" / "recipe_rag" / "processed" / "recipes_clean.json").read_text(encoding="utf-8"))
    target_ids = {r["id"] for r in json.loads((ROOT / "data" / "recipe_rag" / "final" / "recipes_v1.json").read_text(encoding="utf-8"))}
    if args.limit:
        recipes = recipes[: args.limit]
    ids = [r["id"] for r in recipes]
    if len(set(ids)) != len(ids):
        raise SystemExit("có id công thức trùng nhau, dừng lại")

    with connect() as conn:                        # thoát khối `with` bình thường thì COMMIT, có lỗi thì ROLLBACK
        existing = conn.execute("select count(*) from recipe").fetchone()[0]
        if existing and not args.reset:
            raise SystemExit(f"recipe đang có {existing} dòng. Dùng --reset nếu muốn xóa sạch và nạp lại.")
        if args.reset:
            conn.execute("truncate recipe restart identity cascade")   # xóa luôn bảng con nhờ cascade

        with conn.cursor() as cur:
            cur.executemany(
                """insert into recipe (id, name, source_url, image_url, description, servings, time_minutes, difficulty,
                                       prep_steps, cooking_steps, usage_notes, tips, in_target_set)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(r["id"], r["name"], r["url"], r.get("image_url"), r.get("description"),
                  to_int(r.get("servings")), to_int(r.get("time_minutes")), r.get("difficulty"),
                  Jsonb(parse_list(r.get("prep_steps"))), Jsonb(parse_list(r.get("cooking_steps"))),
                  Jsonb(parse_list(r.get("usage_notes"))), Jsonb(parse_list(r.get("tips"))), r["id"] in target_ids)
                 for r in recipes])
            cur.executemany(
                """insert into recipe_ingredient (recipe_id, position, raw_text, name, form, quantity, unit, role, alt)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(r["id"], pos, i.get("raw_text"), i["name"], i.get("form"), i.get("quantity"), i.get("unit"),
                  i["role"], Jsonb(i.get("alt", [])))
                 for r in recipes for pos, i in enumerate(r["ingredients"], start=1)])

        n_recipe, n_ing, n_target, n_null_serv = conn.execute(
            "select (select count(*) from recipe), (select count(*) from recipe_ingredient),"
            " (select count(*) from recipe where in_target_set), (select count(*) from recipe where servings is null)").fetchone()
        print(f"đã nạp: {n_recipe} công thức, {n_ing} dòng nguyên liệu | thuộc 100 món mục tiêu: {n_target} | chưa rõ khẩu phần: {n_null_serv}")
        if args.dry_run:
            conn.rollback()
            print("--dry-run: đã hoàn tác, không lưu gì")


if __name__ == "__main__":
    main()
