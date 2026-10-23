# Module `recipe_rag` (Chef Copilot / Recipe-to-Cart)

Biến câu hỏi như "canh chua cá lóc cho 4 người" thành món + giỏ hàng nguyên liệu có trong catalog. Chi tiết quyết định, số liệu và tự đánh giá: `notebooks/recipe_rag/recipe_matching_pipeline.ipynb`. Cấu trúc chung của repo: `docs/STRUCTURE.md`.

Chạy mọi lệnh từ thư mục `grocery-store-ai`, venv Python 3.11. Script `scripts/recipe_rag/*.py` tự tìm dữ liệu ở `data/recipe_rag/`.

## Thứ tự chạy

| # | Giai đoạn | Script (trong `scripts/recipe_rag/`) | Kết quả chính |
| :-- | :-- | :-- | :-- |
| 1 | Chuẩn hóa | `build_recipes_clean.py`, `build_catalog_clean.py` | `processed/recipes_clean.json`, `catalog_clean.json` |
| 2 | Gợi ý gộp tên | `build_alias_candidates.py` | `processed/alias_candidates.csv` |
| 3 | 100 món mục tiêu | `build_recipe_shortlist.py`, `build_catalog_updates.py` | `processed/recipes_shortlist.json` |
| 4 | Duyệt tay, bảng ghép | `build_ingredient_review.py`, `build_review_v2.py`, `build_ingredient_matches.py` | `review/ingredient_catalog_map_v1.json` |
| 5 | Catalog v2, **khóa id** | `build_catalog_v2.py`, `build_catalog_ids.py`, `build_final_handoff.py` | `review/catalog_ids_v1.json`, `final/*_v1.*` |
| 6 | Mở rộng cho món phổ biến | `suggest_catalog_expansion.py`, `triage_catalog_expansion.py candidates\|apply`, `build_catalog_additions_v2.py`, `check_catalog_duplicates.py`, `dedup_catalog_additions_v2.py`, rồi lại `build_catalog_v2.py`, `build_catalog_ids.py` | 354 sản phẩm mới, CAT-001776..CAT-002129 |
| 7 | Bàn giao v2 | `build_final_handoff_v2.py` | `final/catalog_v2.*`, `recipes_v2.json`, `ingredient_to_catalog_v2.json` |
| 8 | Cơ sở dữ liệu tìm kiếm | `docker compose up -d`, `load_recipes.py`, `embed_recipes.py` | `ai_db`: recipe, recipe_embedding |
| 9 | Thử và đo | `search_recipes.py "..."`, `test_rag_basket.py`, `eval_recipe_search.py` | `review/rag_test_results.json`, `review/recipe_search_eval_v1.json` |

## Quy tắc không được phá

- `data/recipe_rag/review/catalog_ids_v1.json` + `.sha256` là **sổ id khóa cứng** (chỉ-đọc). Không sửa tay, không đổi id; chỉ `build_catalog_ids.py` được nối thêm id mới. **Phải được commit.**
- Giá và ảnh do bên web quản lý; catalog bàn giao không có giá.
- Con số trong notebook là kết quả đo trên dữ liệu hiện tại, không phải mục tiêu proposal.

## Đánh giá tìm món

Bộ câu hỏi: `data/recipe_rag/eval/recipe_queries_v1.json` (108 câu, 7 loại, nhãn là luật theo tên món/nguyên liệu). Chạy `eval_recipe_search.py` để so ILIKE, bge-m3 và hybrid, rồi xem ngưỡng "không tìm thấy". Nhãn do AI soạn nên kết quả có xu hướng lạc quan; cần thêm câu hỏi thật của người dùng.
