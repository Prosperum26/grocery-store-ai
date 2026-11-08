-- Giỏ hàng dựng sẵn và catalog cho ai-service. File này giống db/migrations/002_recipe_basket_and_catalog.sql
-- (init chạy một lần khi volume trống; DB đã có thì áp migration bằng tay).
--   docker exec -i grocery-ai-db psql -U ai_user -d ai_db < db/migrations/002_recipe_basket_and_catalog.sql
-- Dữ liệu nạp bằng scripts/recipe_rag/load_basket_data.py (nguồn: data/recipe_rag/final/*_v2.json).
-- Giá, ảnh, tồn kho KHÔNG ở đây: do Medusa quản lý, ghép theo catalog_id.

-- Catalog bàn giao (catalog_id đã khóa cứng).
CREATE TABLE IF NOT EXISTS catalog_product (
    catalog_id    text PRIMARY KEY,                 -- 'CAT-000123', không đổi
    name          text NOT NULL,
    category      text,
    unit          text,                             -- quy cách hiển thị, vd 'khay 500g'
    pack_size     numeric,                          -- tách từ tên; NULL nếu không đọc được
    pack_unit     text,                             -- g | kg | ml | lít | ...
    needs_review  boolean NOT NULL DEFAULT false,   -- sản phẩm thêm tay, tên/đơn vị là giá trị tạm
    status        text NOT NULL DEFAULT 'active'
);

-- Giỏ dựng sẵn của từng món có giỏ hàng. `ingredients` lấy nguyên từ recipes_matched_v2.json:
-- [{ingredient, kind, raw_text, quantity, unit, status, match:{catalog_id, product_name, ..., packs, match_via, alternatives[]}}]
CREATE TABLE IF NOT EXISTS recipe_basket (
    recipe_id      text PRIMARY KEY REFERENCES recipe(id) ON DELETE CASCADE,
    family         text,                            -- họ món (canh chua, gà nướng...), NULL với món ngoài danh sách phổ biến
    in_target_set  boolean NOT NULL DEFAULT false,
    complete       boolean NOT NULL,                -- mọi nguyên liệu chính đã có sản phẩm
    ingredients    jsonb NOT NULL,
    loaded_at      timestamptz NOT NULL DEFAULT now()
);
