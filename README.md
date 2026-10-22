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
│   ├── raw/
│   ├── processed/
│   └── recipes_vn.json
├── weights/
└── src/
	├── main.py
	├── config/
	├── api/
	│   └── v1/
	├── schemas/
	├── services/
	├── ml/
	└── utils/
```

Các module Python hiện chỉ là skeleton và docstring định hướng. Chưa có logic nghiệp vụ, inference hoặc xử lý API.

## Dữ liệu đã xử lý (predictive reorder)

Cần có sẵn trong `data/raw/` các file `orders.csv`, `order_products__prior.csv` và `order_products__train.csv`. Mọi lệnh chạy từ thư mục gốc của repo, sau khi đã kích hoạt `.venv` (xem [Khởi chạy ban đầu](#khởi-chạy-ban-đầu)). Không chạy từ bên trong `scripts/`, vì code import theo dạng `scripts...`.

### Tạo dữ liệu

```bash
python -m scripts.data_prep --users 20000                    # tập con 20.000 user, seed 42 (mặc định)
python -m scripts.data_prep --users 0                        # toàn bộ user
python -m scripts.data_prep --users 20000 --train-targets 3  # lấy 3 đơn train cuối làm nhãn
python -m scripts.data_prep --users 0 --out-dir data/processed_full  # ghi ra thư mục khác
python -m scripts.data_prep --help                           # xem mọi tùy chọn
```

`src/ml/feature_extractor.py` là thư viện, không chạy riêng. Hàm `extract_features` của nó được `data_prep` gọi tới, và sau này endpoint `/predict` cũng dùng đúng hàm này.

### Chạy baseline

```bash
python -m scripts.baselines --users 20000 --k 10   # popularity và top-frequency cá nhân
```

Dùng đúng user, split và đơn nhãn như `data_prep`. Kết quả in ra bảng precision, recall, F1, hit rate cho từng split và được lưu vào `data/processed/baselines.json`.

### Chạy test

```bash
python -m pytest -q tests                # toàn bộ test
python -m pytest -v tests                # xem kết quả từng test
python -m pytest -v tests -k real        # chỉ các test trên dữ liệu thật
python -m pytest -v tests -k "not real"  # chỉ các test trên dữ liệu đồ chơi (không cần data/raw)
```

Các test trên dữ liệu thật tự bỏ qua nếu chưa có `data/raw/orders.csv`.

### Xem nhanh kết quả

```powershell
Get-Content data\processed\meta.json
python -c "import polars as pl; print(pl.read_parquet('data/processed/train.parquet').head())"
```

### Kết quả

Kết quả là `data/processed/{train,val,test}.parquet` và `meta.json` (không commit). `meta.json` ghi lại thời điểm chạy, seed, `n_users`, `train_targets`, các tham số và thống kê của từng split, để biết bộ parquet hiện có được tạo ra như thế nào. Chi tiết cách lọc, chia split và xử lý giá trị 30 nằm trong docstring của [scripts/data_prep.py](scripts/data_prep.py).

Mỗi dòng là một cặp **(đơn nhãn, sản phẩm candidate)**: liệu user có mua lại sản phẩm này trong đơn nhãn hay không. Candidate là tối đa 100 sản phẩm user đã mua trước đơn nhãn, xếp theo `up_decay`. Mọi feature chỉ dùng các đơn có `order_number < t_order`.

Tên, ý nghĩa và công thức của từng feature, cùng các lượt v0–v4, nằm trong [docs/features.md](docs/features.md). Kết quả thí nghiệm ghi trong [docs/experiments.md](docs/experiments.md).

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
