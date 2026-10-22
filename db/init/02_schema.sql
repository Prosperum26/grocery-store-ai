-- Schema ai_db: công thức, nguyên liệu và embedding (bge-m3, 1024 chiều).
-- Nguồn dữ liệu: data/processed/recipes_clean.json (xem scripts/build_recipes_clean.py).
-- ai_db KHÔNG giữ catalog hay giỏ hàng: ghép nguyên liệu -> sản phẩm do Medusa quản lý (theo catalog_id).

-- Một dòng cho mỗi công thức.
CREATE TABLE recipe (
    id                 text PRIMARY KEY,               -- slug lấy từ URL nguồn, ổn định, ví dụ 'canh-chua-ca-loc'
    name               text NOT NULL,
    source_url         text NOT NULL UNIQUE,
    image_url          text,
    description        text,
    servings           integer CHECK (servings IS NULL OR servings > 0),  -- NULL khi nguồn ghi 0 hoặc thiếu
    time_minutes       integer,
    difficulty         text,
    prep_steps         jsonb NOT NULL DEFAULT '[]',    -- danh sách chuỗi
    cooking_steps      jsonb NOT NULL DEFAULT '[]',
    usage_notes        jsonb NOT NULL DEFAULT '[]',
    tips               jsonb NOT NULL DEFAULT '[]',
    in_target_set      boolean NOT NULL DEFAULT false, -- thuộc 100 món mục tiêu đã có giỏ hàng (data/final/recipes_v1.json)
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Nguyên liệu đã chuẩn hóa của mỗi công thức (một dòng thô có thể thành nhiều dòng sau khi tách danh sách).
CREATE TABLE recipe_ingredient (
    id          bigserial PRIMARY KEY,
    recipe_id   text NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    position    integer NOT NULL,                       -- thứ tự xuất hiện trong công thức
    raw_text    text,                                   -- dòng gốc, để truy vết khi chuẩn hóa sai
    name        text NOT NULL,                          -- tên chuẩn hóa: khóa ghép với catalog
    form        text CHECK (form IN ('phi', 'xay', 'rang')),  -- dạng dễ làm tại nhà, đã gộp về tên gốc
    quantity    numeric,
    unit        text,
    role        text NOT NULL CHECK (role IN ('main', 'side')),  -- side = ăn kèm / rau nêm / trang trí
    alt         jsonb NOT NULL DEFAULT '[]',            -- lựa chọn thay thế ("A hoặc B")
    UNIQUE (recipe_id, position)
);
CREATE INDEX recipe_ingredient_name_idx ON recipe_ingredient (name);

-- Vector embedding. Hai loại chunk, theo proposal:
--   'card'       1 chunk mỗi công thức (tên món, mô tả, khẩu phần, nguyên liệu chính)
--   'ingredient' 1 chunk mỗi dòng nguyên liệu (ingredient_id bắt buộc)
CREATE TABLE recipe_embedding (
    id             bigserial PRIMARY KEY,
    recipe_id      text NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    ingredient_id  bigint REFERENCES recipe_ingredient(id) ON DELETE CASCADE,
    chunk_type     text NOT NULL CHECK (chunk_type IN ('card', 'ingredient')),
    content        text NOT NULL,                       -- đúng chuỗi đã đưa vào model, để kiểm tra và embed lại
    embedding      vector(1024) NOT NULL,
    model          text NOT NULL DEFAULT 'BAAI/bge-m3',
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK ((chunk_type = 'ingredient') = (ingredient_id IS NOT NULL))
);
-- Mỗi công thức đúng 1 card, mỗi dòng nguyên liệu tối đa 1 chunk: để nạp lại (upsert) không bị nhân đôi.
CREATE UNIQUE INDEX recipe_embedding_card_uq ON recipe_embedding (recipe_id) WHERE chunk_type = 'card';
CREATE UNIQUE INDEX recipe_embedding_ingredient_uq ON recipe_embedding (ingredient_id) WHERE chunk_type = 'ingredient';
CREATE INDEX recipe_embedding_recipe_idx ON recipe_embedding (recipe_id);

-- Chỉ mục vector HNSW theo cosine (khớp toán tử <=> và vector đã chuẩn hóa của bge-m3).
-- MỖI LOẠI CHUNK MỘT CHỈ MỤC RIÊNG (chỉ mục từng phần). Không dùng một chỉ mục chung: HNSW chỉ trả về
-- khoảng 40 vector gần nhất (hnsw.ef_search) TRONG TOÀN BẢNG rồi mới áp bộ lọc `where chunk_type = ...`.
-- Câu hỏi ngắn ("canh chua") gần với các tên nguyên liệu ngắn hơn là thẻ món, nên 40 kết quả đó toàn là
-- chunk 'ingredient' và bị lọc hết, tìm thẻ món ra 0 dòng. Chỉ mục từng phần chỉ chứa đúng một loại chunk.
-- Truy vấn PHẢI có điều kiện `chunk_type = 'card'` (hoặc 'ingredient') ghi thẳng như hằng số để dùng được chỉ mục này.
-- Với ~2,5 nghìn thẻ món, quét chính xác cũng chỉ vài ms; chỉ mục có để đo xem có đáng dùng không (xem notebook).
CREATE INDEX recipe_embedding_card_hnsw_idx ON recipe_embedding
    USING hnsw (embedding vector_cosine_ops) WHERE chunk_type = 'card';
CREATE INDEX recipe_embedding_ingredient_hnsw_idx ON recipe_embedding
    USING hnsw (embedding vector_cosine_ops) WHERE chunk_type = 'ingredient';
