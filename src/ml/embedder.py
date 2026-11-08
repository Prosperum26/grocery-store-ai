"""Embedding câu hỏi bằng bge-m3. Nạp model một lần, dùng lại cho mọi yêu cầu."""
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")     # model đã nằm trong cache Hugging Face, không hỏi mạng

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


class Embedder:
    def __init__(self, model_name: str):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = SentenceTransformer(model_name, device=self.device)
        if self.device == "cuda":
            self._model.half()                    # fp16: nhanh hơn, vừa VRAM 6 GB

    def encode(self, text: str) -> np.ndarray:
        """Vector 1024 chiều đã chuẩn hóa (cosine = tích vô hướng)."""
        return self._model.encode([text], normalize_embeddings=True)[0]
