-- Migration 001: thay chỉ mục HNSW chung bằng hai chỉ mục từng phần (mỗi loại chunk một cái).
-- Lý do: chỉ mục chung làm tìm thẻ món trả về 0 dòng với câu hỏi ngắn (xem chú thích trong db/init/02_schema.sql).
-- Chỉ chạy cho database ĐÃ TẠO từ schema cũ (db/init chỉ chạy lúc khởi tạo). Chạy lại nhiều lần vẫn an toàn.
--   Get-Content db\migrations\001_partial_hnsw_per_chunk_type.sql | docker exec -i grocery-ai-db psql -U ai_user -d ai_db
SET maintenance_work_mem = '512MB';   -- để dựng HNSW nhanh hơn (mặc định 64MB không đủ chứa đồ thị)
BEGIN;
DROP INDEX IF EXISTS recipe_embedding_hnsw_idx;
CREATE INDEX IF NOT EXISTS recipe_embedding_card_hnsw_idx ON recipe_embedding
    USING hnsw (embedding vector_cosine_ops) WHERE chunk_type = 'card';
CREATE INDEX IF NOT EXISTS recipe_embedding_ingredient_hnsw_idx ON recipe_embedding
    USING hnsw (embedding vector_cosine_ops) WHERE chunk_type = 'ingredient';
COMMIT;
