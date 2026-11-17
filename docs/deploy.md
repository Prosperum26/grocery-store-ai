# Deploy ai-service

Chạy trên **Hugging Face Spaces** (Docker SDK, CPU basic free: 2 vCPU, 16 GB RAM). `Dockerfile` dựng image
cho app gộp `src.main` ở cổng 7860, tải sẵn bge-m3 vào image. `ai_db` đặt trên Neon (pgvector).

- CI: `.github/workflows/ci.yml` chạy `pytest tests` (torch bản CPU) cho push/PR vào `dev`/`main`.
- CD: `.github/workflows/deploy-hf.yml` đẩy `src/`, `weights/` (phần có trong git), `requirements.txt`,
  `Dockerfile` sang Space khi push lên `main`. Cần secret `HF_TOKEN` và variable `HF_SPACE` (`<user>/<space>`).
  Workflow chỉ thêm/ghi đè file nên model `weights/lgbm_v4_selected.onnx` upload tay một lần vẫn còn.

Biến trên Space (Settings > Variables and secrets): `AI_DB_HOST`, `AI_DB_PORT=5432`, `AI_DB_NAME`, `AI_DB_USER`,
`AI_DB_PASSWORD`, `PGSSLMODE=require`, `GEMINI_API_KEY`, `AI_INTERNAL_KEY` (giống backend).

Space free ngủ sau 48 giờ không có request; pinger ở repo backend có thể gọi `/api/v1/health` của Space.
Hướng dẫn đầy đủ: `docs/deploy.md` của repo `grocery-store-backend`.
