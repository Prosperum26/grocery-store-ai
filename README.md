# grocery-store-ai - AI & Analytics Microservice

Microservice AI độc lập cho đồ án MSIS4133 (Công nghệ thông tin trong Thương mại điện tử, UIT). Service này sử dụng Python 3.11 và FastAPI, giao tiếp với Core Backend qua HTTP REST API.

## Bối cảnh hệ thống

Hệ thống được tổ chức thành ba repository độc lập:

1. `grocery-store-frontend`: giao diện người dùng Next.js / React.
2. `grocery-store-backend`: Core Backend NestJS, cơ sở dữ liệu, xác thực và đơn hàng.
3. `grocery-store-ai`: microservice Python xử lý AI và analytics.

Repository này được chuẩn bị cho hai hướng phát triển:

- `feature/predictive-reorder`: dự đoán chu kỳ mua lại bằng LightGBM, Polars và ONNX.
- `feature/recipe-rag-copilot`: tìm kiếm ngữ nghĩa công thức và trợ lý bếp Gemini.

## Môi trường yêu cầu

- Python 3.11.9
- pip
- Git

## Cấu trúc thư mục

```text
grocery-store-ai/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── notebooks/
├── data/
│   ├── raw/                      # CSV Instacart (không commit)
│   └── processed/                # parquet, kết quả chạy (không commit)
├── docs/
│   ├── report.md                 # báo cáo predictive reorder
│   ├── features.md               # bảng mô tả feature
│   ├── experiments.md            # nhật ký thí nghiệm
│   └── figures/
├── scripts/
│   ├── data_prep.py              # lọc dữ liệu, chia split, candidate
│   ├── baselines.py              # popularity, personal_freq, TIFU-KNN
│   ├── tifuknn.py
│   ├── train_lgbm.py             # train, ablation, inspect
│   ├── select_threshold.py       # chọn τ, calibration
│   ├── final_eval.py             # model gate trên test
│   ├── eval_topk.py              # so sánh @5, @10, @15 kèm bootstrap (chỉ val)
│   ├── run_pipeline.py           # chạy cả pipeline từ data/raw
│   └── onnx_probe.py
├── tests/
├── weights/                      # model (không commit), model_metadata.json (commit)
└── src/
    ├── main.py
    ├── config/
    ├── api/
    │   └── v1/
    ├── schemas/
    ├── services/
    ├── ml/
    │   └── feature_extractor.py  # extract_features: dùng chung cho train và /predict
    └── utils/
```

Phần predictive reorder (chuẩn bị dữ liệu, feature, baseline, LightGBM) đã có code, nằm ở `scripts/` và `src/ml/feature_extractor.py`. Các module API (`src/api`, `src/services`) vẫn chỉ là skeleton.

## Predictive reorder: dự đoán mua lại

Gợi ý cho mỗi khách tối đa 15 món họ **đã từng mua** và nhiều khả năng sẽ mua trong đơn tiếp theo. Dữ liệu là bộ Instacart, mô hình là LightGBM.

**Kết quả hiện tại** (20.000 khách, chạy test một lần): LightGBM đạt Recall@15 = **0,431** và NDCG@15 = **0,449**, vượt baseline tốt nhất là TIFU-KNN (0,417 và 0,433). **Model gate: QUA.** Chi tiết trong [docs/report.md](docs/report.md).

### Cách hoạt động (tóm tắt)

1. **Chuẩn bị dữ liệu** ([scripts/data_prep.py](scripts/data_prep.py)):
   - gộp lịch sử mua và giữ khách có ít nhất 5 đơn;
   - chia split theo từng khách: đơn cuối là test, đơn kế cuối là val, các đơn trước là train.
2. **Candidate**: với mỗi đơn cần dự đoán, lấy tối đa 100 món khách đã mua trước đó.
3. **Feature** ([src/ml/feature_extractor.py](src/ml/feature_extractor.py)): 23 con số cho mỗi cặp (khách, món), như số lần mua, độ gần đây và nhịp mua. Feature chỉ dùng các đơn trước thời điểm dự đoán. Mô tả trong [docs/features.md](docs/features.md).
4. **LightGBM** chấm xác suất được mua lại cho từng candidate, rồi xếp hạng.
5. **Ngưỡng τ**: gợi ý các món nằm trong top-15 và có xác suất ≥ τ. Hiện τ = 0,13, đọc từ `weights/model_metadata.json`.

### Yêu cầu

- Trong `data/raw/` cần có các file `orders.csv`, `order_products__prior.csv`, `order_products__train.csv` và `products.csv` của Instacart.
- Đã kích hoạt `.venv` (xem [Khởi chạy ban đầu](#khởi-chạy-ban-đầu)).
- Mọi lệnh chạy **từ thư mục gốc của repo**. Không chạy từ bên trong `scripts/`, vì code import theo dạng `scripts...` và `src...`.

### Chạy toàn bộ pipeline

Chạy lần lượt từ trên xuống:

| Bước                                    | Lệnh                                                                      | Thời gian | Kết quả                                          |
| ----------------------------------------- | -------------------------------------------------------------------------- | ---------- | -------------------------------------------------- |
| 0. Kiểm tra code                         | `python -m pytest -q tests`                                              | ~10 giây  | tất cả test pass                                 |
| 1. Dữ liệu (nhãn T−2, T−3, T−4)     | `python -m scripts.data_prep --users 20000`                              | ~1 phút   | `data/processed/`                                |
| 2. Baseline (val)                         | `python -m scripts.baselines --users 20000`                              | ~3 phút   | `data/processed/baselines.json`                  |
| 3. Train model đã chọn                 | `python -m scripts.train_lgbm --versions v4 --tag selected --save-model` | ~1 phút   | `weights/lgbm_v4_selected.txt`                   |
| 4. Chọn τ và kiểm tra calibration     | `python -m scripts.select_threshold`                                     | ~30 giây  | `weights/model_metadata.json`, `docs/figures/` |
| 5. So sánh @5, @10, @15 (val)            | `python -m scripts.eval_topk`                                            | ~3 phút   | `data/processed/topk_val.json`                   |
| 6. Model gate (test, **một lần**) | `python -m scripts.final_eval`                                           | ~2 phút   | `data/processed/final_test.json`                 |

Hoặc chạy tất cả, kể cả ablation, bằng `python -m scripts.run_pipeline`.

Chỉ giữ một bộ dữ liệu trong `data/processed/`. Bộ `train_targets = 1` cho ablation được tạo tạm rồi xóa.

**Về bước 6**: test chỉ được dùng một lần. Nếu `data/processed/final_test.json` đã tồn tại, script sẽ từ chối chạy lại. Muốn xem kết quả thì đọc file đó:

```powershell
Get-Content data\processed\final_test.json
```

Chỉ xóa file này khi làm lại từ đầu với cấu hình đã chốt sẵn (ví dụ chạy trên toàn bộ khách). Không xóa để thử lại sau khi đổi model.

### Thử nghiệm (chỉ nhìn val)

```bash
python -m scripts.data_prep --users 20000 --train-targets 1 --out-dir data/processed_tt1   # dữ liệu tạm cho ablation
python -m scripts.train_lgbm --versions v0,v1,v2,v3,v4 --data-dir data/processed_tt1      # ablation theo lượt feature
python -m scripts.train_lgbm --versions v4 --inspect 5                        # feature importance + top-15 của 5 khách
python -m scripts.train_lgbm --versions v4 --num-leaves 127 --tag leaves127   # thử một thay đổi
python -m scripts.baselines --users 20000 --group-size 7 --alpha 0.9          # thử tham số TIFU-KNN
python -m scripts.onnx_probe                                                  # kiểm tra chuyển LightGBM sang ONNX
```

- Mỗi lần chỉ đổi một thứ.
- Ghi kết quả vào [docs/experiments.md](docs/experiments.md).
- Mỗi lần train được ghi thêm một dòng vào `<data-dir>/lgbm_runs.jsonl`.
- Không dùng `--eval-test` khi đang thử nghiệm.
- Thêm `--help` vào bất kỳ lệnh nào để xem mọi tùy chọn.

Các tùy chọn khác của `data_prep`:

```bash
python -m scripts.data_prep --users 0                                # toàn bộ khách
python -m scripts.data_prep --users 0 --out-dir data/processed_full  # ghi ra thư mục khác
```

### Chạy test

```bash
python -m pytest -q tests                # toàn bộ test
python -m pytest -v tests -k real        # chỉ các test trên dữ liệu thật
python -m pytest -v tests -k "not real"  # chỉ các test trên dữ liệu đồ chơi (không cần data/raw)
```

Các test trên dữ liệu thật tự bỏ qua nếu chưa có `data/raw/orders.csv`.

### Kiểm tra nhanh

Nếu đã có sẵn dữ liệu và model, lệnh sau phải ra NDCG@15 ≈ **0,4505** trên val:

```bash
python -m scripts.train_lgbm --versions v4
```

### File đầu ra

| File                                                        | Nội dung                                                                               | Commit?       |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------- |
| `data/processed/{train,val,test}.parquet`                 | Mỗi dòng là một cặp (đơn cần dự đoán, món candidate): feature và `label` | Không        |
| `data/processed/{split}_truth.parquet`                    | Giỏ hàng thật đầy đủ của từng đơn, kể cả món mới, để tính metric      | Không        |
| `data/processed/meta.json`                                | Seed, số khách, tham số và thống kê của lần tạo dữ liệu                      | Không        |
| `data/processed/baselines.json`                           | Kết quả của 3 baseline                                                               | Không        |
| `data/processed/lgbm_runs.jsonl`                          | Một dòng cho mỗi lần train                                                          | Không        |
| `data/processed/final_test.json`                          | Kết quả của lần chạy test duy nhất                                                | Không        |
| `weights/lgbm_v4_selected.txt`                            | Model LightGBM đã chọn                                                               | Không        |
| `weights/model_metadata.json`                             | τ, danh sách feature, tên file model, calibration                                    | **Có** |
| `docs/figures/reliability_val.png`, `tau_curve_val.png` | Reliability diagram, đường cong τ                                                   | Có           |

### Phục vụ dự đoán

```bash
python -m scripts.export_onnx            # weights/lgbm_v4_selected.onnx, kiểm tra parity trên val
python -m scripts.build_category_stats   # weights/category_stats.json, mô phỏng trên val
python -m scripts.bench_latency          # latency CPU, đối chiếu feature train/serve
uvicorn src.main:app --reload
```

```bash
curl -X POST http://localhost:8000/api/v1/predict -H "Content-Type: application/json" -d '{
  "orders": [{"placed_at": "2026-10-01T09:00:00+07:00",
              "lines": [{"product_id": "prod_1", "category": "rau-cu"}]}],
  "at": "2026-10-20T09:00:00+07:00", "top_k": 5}'
```

Thiếu file model hoặc thống kê thì service vẫn chạy và `/predict` trả 503. Endpoint chưa có xác thực, chỉ dùng trong mạng nội bộ.

### Tài liệu

| File                                                    | Nội dung                                                                 |
| ------------------------------------------------------- | ------------------------------------------------------------------------- |
| [docs/report.md](docs/report.md)                         | Báo cáo kết quả và kết luận của model gate                        |
| [docs/features.md](docs/features.md)                     | Tên, ý nghĩa và công thức của từng feature, các lượt v0–v4    |
| [docs/experiments.md](docs/experiments.md)               | Nhật ký thí nghiệm: baseline, ablation, tune, τ                      |
| [scripts/data_prep.py](scripts/data_prep.py) (docstring) | Cách lọc dữ liệu, chia split, xử lý `days_since_prior_order = 30` |

## Khởi chạy ban đầu

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn src.main:app --reload
```

Nếu PowerShell chặn `Activate.ps1` vì không cho chạy script, chạy lệnh sau một lần rồi kích hoạt lại:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn src.main:app --reload
```

Sau khi phần application được triển khai, Swagger UI sẽ dùng tại `http://localhost:8000/docs`.

## Cấu hình môi trường

Sao chép `.env.example` thành `.env` và cập nhật các giá trị phù hợp với môi trường local. Không commit `.env` hoặc API key lên Git.

## Chiến lược phân nhánh Git

- `main`: nhánh ổn định, chỉ merge sau khi nhóm thống nhất và kiểm tra thay đổi.
- `feature/predictive-reorder`: phát triển tính năng dự đoán mua lại trong `src/api/v1/reorder.py`, `src/services/reorder_service.py` và `src/ml/feature_extractor.py` / `src/ml/onnx_inference.py`.
- `feature/recipe-rag-copilot`: phát triển RAG công thức và trợ lý bếp Gemini trong `src/api/v1/recipes.py`, `src/api/v1/copilot.py`, `src/services/recipe_service.py`, `src/services/gemini_service.py` và `src/ml/embedder.py`.

Mỗi nhánh feature nên được cập nhật từ `main`, giữ commit tập trung theo một mục tiêu và tạo pull request trước khi merge.

## Trạng thái khởi tạo

Đây là boilerplate ban đầu. Các endpoint, schema Pydantic, model AI và tích hợp Gemini sẽ được triển khai ở các nhánh feature tương ứng.
