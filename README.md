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
