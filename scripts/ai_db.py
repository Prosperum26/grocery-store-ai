"""Kết nối ai_db dùng chung cho các script nạp, embed và tìm kiếm.

Đọc cấu hình từ file .env (AI_DB_HOST, AI_DB_PORT, AI_DB_NAME, AI_DB_USER, AI_DB_PASSWORD); xem .env.example.
Cần Docker đang chạy container ai_db:  docker compose up -d
"""
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parents[1]


def connect():
    """Mở kết nối tới ai_db và bật kiểu `vector` (để truyền numpy array thẳng vào SQL)."""
    env = dotenv_values(ROOT / ".env")
    missing = [k for k in ("AI_DB_HOST", "AI_DB_PORT", "AI_DB_NAME", "AI_DB_USER", "AI_DB_PASSWORD") if not env.get(k)]
    if missing:
        raise SystemExit(f"Thiếu {', '.join(missing)} trong .env (copy từ .env.example)")
    try:
        conn = psycopg.connect(host=env["AI_DB_HOST"], port=env["AI_DB_PORT"], dbname=env["AI_DB_NAME"],
                               user=env["AI_DB_USER"], password=env["AI_DB_PASSWORD"], connect_timeout=5)
    except psycopg.OperationalError as e:
        raise SystemExit(f"Không nối được ai_db ({e.__class__.__name__}). Docker đã bật chưa? Chạy: docker compose up -d")
    register_vector(conn)
    return conn
