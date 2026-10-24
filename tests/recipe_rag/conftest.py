"""Đưa thư mục gốc vào sys.path để import được `src` khi chạy `pytest tests/recipe_rag` từ gốc repo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
