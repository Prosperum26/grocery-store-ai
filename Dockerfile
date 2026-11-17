# Image cho Hugging Face Spaces (Docker SDK, CPU free: 2 vCPU, 16 GB RAM, cổng 7860).
# Chạy app gộp src.main (Trợ lý Bếp + Mua lại). Xem docs/deploy.md.
FROM python:3.11-slim

# Spaces chạy container bằng user uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

# torch bản CPU cài trước (nhỏ hơn nhiều so với bản kèm CUDA), rồi tới phần còn lại.
COPY requirements.txt .
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

# Tải sẵn bge-m3 vào image để lần khởi động sau khi Space ngủ không phải tải lại ~2 GB.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY --chown=user src/ src/
# weights/ chứa model ONNX của "Mua lại" (không có trong GitHub, upload tay lên Space một lần).
COPY --chown=user weights/ weights/
RUN chown -R user /app/.cache

USER user
EXPOSE 7860
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7860"]
