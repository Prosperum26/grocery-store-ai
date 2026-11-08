-- Chạy trong database ai_db (do biến POSTGRES_DB tạo ra).
-- pgvector: kiểu `vector` và các toán tử khoảng cách (<=> cosine, <-> L2, <#> tích vô hướng âm).
CREATE EXTENSION IF NOT EXISTS vector;
