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

Tạo dữ liệu từ bộ Instacart trong `data/raw/`:

```bash
python -m src.ml.data_prep --users 20000   # tập con 20.000 user, seed 42
python -m src.ml.data_prep --users 0       # toàn bộ user
```

Kết quả là `data/processed/{train,val,test}.parquet` (không commit). Chi tiết cách lọc, chia split và xử lý giá trị 30 nằm trong docstring của [src/ml/data_prep.py](src/ml/data_prep.py).

Mỗi dòng là một cặp **(đơn nhãn, sản phẩm candidate)**: liệu user có mua lại sản phẩm này trong đơn nhãn hay không. Candidate là tối đa 100 sản phẩm user đã mua trước đơn nhãn, xếp theo `up_decay`. Mọi feature chỉ dùng các đơn có `order_number < t_order`.

Quy ước tiền tố: `up_` = user × sản phẩm, `u_` = user, `p_` = sản phẩm (toàn cục), `t_` = đơn nhãn. "Đơn trước" luôn là các đơn trước đơn nhãn.

### Khóa và nhãn

| Cột | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `user_id` | int | Mã người dùng |
| `t_order` | int | `order_number` của đơn nhãn (đơn cần dự đoán) |
| `product_id` | int | Mã sản phẩm candidate |
| `label` | 0/1 | 1 nếu sản phẩm có trong đơn nhãn, 0 nếu không |
| `up_last_order` | int | `order_number` lần gần nhất user mua sản phẩm. Dùng để kiểm tra rò rỉ (luôn < `t_order`), không đưa vào model |

### Feature user × sản phẩm

| Cột | Ý nghĩa |
| --- | --- |
| `up_cnt` | Số đơn trước có sản phẩm này |
| `up_rate` | `up_cnt / u_n_orders`: tỉ lệ đơn có sản phẩm |
| `up_orders_since` | Số đơn kể từ lần mua gần nhất (`t_order - up_last_order`) |
| `up_days_since` | Số ngày kể từ lần mua gần nhất. Là cận dưới nếu có khoảng cách bị chặn ở 30 |
| `up_mean_gap` | Số ngày trung bình giữa hai lần mua liên tiếp. Null nếu mới mua một lần |
| `streak_ratio` | `up_days_since / up_mean_gap`. Gần 1 nghĩa là "đến lúc mua lại". Null nếu không biết khoảng cách hoặc khoảng cách bằng 0 |
| `up_decay` | Tổng `0.9^k` của các lần mua, với k là số đơn tính từ lần mua đó đến đơn nhãn. Mua càng gần, càng nhiều thì càng lớn. Dùng để chọn top 100 candidate |
| `up_avg_cart_pos` | Vị trí trung bình trong giỏ (`add_to_cart_order`). Nhỏ nghĩa là thường được thêm vào giỏ sớm |
| `up_first_order` | `order_number` lần đầu mua sản phẩm |
| `in_last_1`, `in_last_2`, `in_last_3` | 1 nếu sản phẩm có trong 1, 2 hoặc 3 đơn gần nhất |

### Feature user

| Cột | Ý nghĩa |
| --- | --- |
| `u_n_orders` | Số đơn trước đơn nhãn (= `t_order - 1`) |
| `u_basket` | Số món trung bình mỗi đơn |
| `u_reorder_rate` | Tỉ lệ món là hàng mua lại (`reordered = 1`) |
| `u_n_products` | Số sản phẩm khác nhau user đã mua |
| `u_mean_dsp` | Số ngày trung bình giữa các đơn (không tính đơn đầu) |
| `u_pct_capped` | Tỉ lệ khoảng cách giữa các đơn bị chặn ở 30 (≥ 30 ngày) |

### Feature sản phẩm (toàn cục)

Chỉ tính từ các đơn không bao giờ làm nhãn, để giỏ hàng val/test của user khác không lọt vào.

| Cột | Ý nghĩa |
| --- | --- |
| `p_cnt` | Số lần sản phẩm được mua |
| `p_reorder_ratio` | Tỉ lệ lần mua là mua lại |
| `p_avg_cart_pos` | Vị trí trung bình trong giỏ |
| `p_n_users` | Số user khác nhau đã mua |

### Bối cảnh đơn nhãn

| Cột | Ý nghĩa |
| --- | --- |
| `t_dow` | Thứ trong tuần của đơn nhãn (0–6) |
| `t_hour` | Giờ đặt đơn nhãn (0–23) |
| `t_dsp` | Số ngày từ đơn trước đến đơn nhãn (`days_since_prior_order`). 30 nghĩa là ≥ 30 |
| `t_dsp_capped` | 1 nếu `t_dsp` bị chặn ở 30 |

## Khởi chạy ban đầu

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn src.main:app --reload
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
