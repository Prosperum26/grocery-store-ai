# Cấu trúc repo `grocery-store-ai`

Repo chứa **một FastAPI service** nhưng có **hai module AI làm việc rất khác nhau**. Quy ước dưới đây để hai nhánh không đè lên nhau khi merge.

| Module | Nhánh | Kiểu công việc | Hạ tầng |
| :-- | :-- | :-- | :-- |
| `recipe_rag` | `feature/recipe-rag-copilot` | Pipeline dữ liệu + embedding bge-m3 + tìm kiếm pgvector + Gemini | Postgres + pgvector (`docker compose`), GPU tùy chọn |
| `reorder` | `feature/predictive-reorder` | Feature engineering, LightGBM, xuất ONNX, dự đoán giỏ mua lại | Polars, LightGBM, ONNX Runtime, (Redis ở backend) |

## Quy tắc đặt tên: mọi thứ của module nằm dưới thư mục mang tên module

```text
grocery-store-ai/
├── src/                      # CHUNG: mã FastAPI chạy thật (route mỏng -> service -> ml)
│   ├── api/v1/               #   recipes.py, copilot.py (recipe_rag) | reorder.py (reorder) | health.py (chung)
│   ├── services/             #   recipe_service.py, gemini_service.py | reorder_service.py
│   ├── ml/                   #   embedder.py (recipe_rag) | feature_extractor.py, onnx_inference.py (reorder)
│   ├── schemas/              #   recipe_dto.py, copilot_dto.py | reorder_dto.py
│   └── config/, utils/       #   chung
├── scripts/
│   ├── recipe_rag/           # pipeline dữ liệu, nạp/embed/tìm kiếm, đánh giá (chạy tay, không vào service)
│   └── reorder/              # data_prep, baselines, tifuknn, huấn luyện LightGBM, đọc Instacart
├── data/
│   ├── recipe_rag/{raw,processed,review,final,eval}/
│   └── reorder/{raw,processed}/
├── notebooks/{recipe_rag,reorder}/
├── docs/{recipe_rag,reorder}/ # + file chung như STRUCTURE.md
├── tests/{recipe_rag,reorder}/
├── weights/                  # mô hình (.onnx...), không commit
├── db/, docker-compose.yml   # hạ tầng ai_db (hiện chỉ recipe_rag dùng)
└── requirements*.txt         # xem bên dưới
```

### Vì sao tách như vậy
- `src/` là mã **chạy trong service**; `scripts/` là mã **chạy ngoài service** để tạo dữ liệu/mô hình. Hai thư mục này không trộn.
- Thư mục theo tên module nên hai nhánh không tạo cùng tên file ở cùng chỗ. Merge hai nhánh chỉ còn xung đột ở file chung (`README.md`, `.gitignore`, `requirements.txt`, `src/main.py`).
- Mỗi script tự tính `ROOT = parents[2]` (tính từ `scripts/<module>/x.py`), dữ liệu của module nằm ở `ROOT/data/<module>/`.

### `.gitignore`: cái gì commit, cái gì không
- **Không commit:** `data/<module>/raw/`, `data/<module>/processed/`, `*.rar`, `weights/*`, `.onnx .parquet .npy .pkl .joblib`, `.env`.
- **Có commit** (module `recipe_rag`): `data/recipe_rag/review/` (kể cả `catalog_ids_v1.json` và `.sha256`, là sổ id khóa cứng, **mất là không khôi phục được**), `data/recipe_rag/final/` (bộ bàn giao cho web), `data/recipe_rag/eval/` (bộ câu hỏi có nhãn).
- Module `reorder` nên làm tương tự: thứ gì tái tạo được từ code + dữ liệu thô thì không commit; thứ gì là quyết định/nhãn/bàn giao thì commit.

### Requirements
- `requirements.txt`: phần chạy service (FastAPI, Pydantic...). Cả hai module dùng.
- `requirements-data.txt`, `requirements-gpu.txt`: chỉ `recipe_rag` (openpyxl, sentence-transformers, torch CUDA, psycopg...).
- Module `reorder` thêm `requirements-reorder.txt` (polars, lightgbm, onnxruntime, scikit-learn...) thay vì nhét vào `requirements.txt`, để service nhẹ và hai module không kéo thư viện của nhau.

## Hướng dẫn cho nhánh `feature/predictive-reorder`

Nhánh này hiện đặt file như sau; chuyển sang cấu trúc trên (dùng `git mv` để giữ lịch sử):

| Hiện tại | Chuyển thành |
| :-- | :-- |
| `scripts/baselines.py` | `scripts/reorder/baselines.py` |
| `scripts/data_prep.py` | `scripts/reorder/data_prep.py` |
| `scripts/tifuknn.py` | `scripts/reorder/tifuknn.py` |
| `scripts/Instacart_Market_Basket_Analysis/read_polar.py` | `scripts/reorder/read_polar.py` |
| `tests/test_baselines.py`, `test_data_prep.py`, `test_feature_extractor.py` | `tests/reorder/...` |
| `docs/experiments.md`, `docs/features.md` | `docs/reorder/experiments.md`, `docs/reorder/features.md` |
| dữ liệu Instacart trong `data/raw/`, `data/processed/` | `data/reorder/raw/`, `data/reorder/processed/` |

Sau khi chuyển: sửa đường dẫn trong script (`ROOT / "data" / "reorder"`), và nhớ chạy test từ thư mục gốc (`pytest tests/reorder`). Có thể dùng `scripts/recipe_rag/build_recipes_clean.py` làm mẫu cách khai báo `ROOT` và đường dẫn dữ liệu.

Các file `src/*` đã có sẵn khung riêng cho từng module nên **không cần di chuyển**; chỉ điền logic vào `reorder_service.py`, `feature_extractor.py`, `onnx_inference.py`, `reorder_dto.py`, `api/v1/reorder.py`.
