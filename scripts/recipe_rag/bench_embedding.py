"""Đo tốc độ embed bge-m3 trên GPU (hoặc CPU) với đúng loại dữ liệu sẽ nạp vào ai_db.

Chạy từ thư mục grocery-store-ai:
    .venv\\Scripts\\python scripts\\recipe_rag\\bench_embedding.py            # GPU (mặc định nếu có CUDA)
    .venv\\Scripts\\python scripts\\recipe_rag\\bench_embedding.py --device cpu  # CPU, chậm (vài phút)
Cần model đã có trong cache Hugging Face (lần đầu chạy build_alias_candidates.py đã tải).

Đo 3 thứ:
  1. 'names'  tên nguyên liệu và tên loại hàng catalog (chuỗi ngắn), như bước gợi ý gộp tên
  2. 'cards'  thẻ món: tên + mô tả + nguyên liệu chính (~300 ký tự), loại chunk 'card' trong ai_db
  3. 'query'  một câu hỏi lẻ (độ trễ thật lúc người dùng tìm kiếm)
Trên GPU còn so vector fp16 với fp32 (CPU) để chắc dùng fp16 không làm lệch kết quả.
Kết quả ghi ở data/recipe_rag/processed/bench_embedding_<device>.json (thư mục này bị .gitignore chặn).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "recipe_rag" / "processed"
MODEL = "BAAI/bge-m3"


def card_text(recipe):
    """Nội dung thẻ món: tên, mô tả, các nguyên liệu chính (cắt 300 ký tự để thẻ không quá dài)."""
    main = ", ".join(i["name"] for i in recipe["ingredients"] if i["role"] == "main")[:300]
    return f"{recipe['name']}. {recipe.get('description') or ''} Nguyên liệu: {main}"


def timed(model, texts, batch_size, device):
    if device == "cuda":
        torch.cuda.synchronize()
    start = time.time()
    vectors = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    if device == "cuda":
        torch.cuda.synchronize()
    return vectors, time.time() - start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda" if torch.cuda.is_available() else "cpu")
    device = parser.parse_args().device

    recipes = json.loads((PROC / "recipes_clean.json").read_text(encoding="utf-8"))
    catalog = json.loads((PROC / "catalog_clean.json").read_text(encoding="utf-8"))
    names = sorted({i["name"] for r in recipes for i in r["ingredients"]} | {p["base"] for p in catalog})
    cards = [card_text(r) for r in recipes]

    start = time.time()
    model = SentenceTransformer(MODEL, device=device)
    if device == "cuda":
        model.half()                                   # fp16: nhanh hơn, ít VRAM hơn
    load_s = time.time() - start
    model.encode(names[:64], batch_size=64)            # khởi động (warm-up), không tính giờ

    v_names, t_names = timed(model, names, 64, device)
    v_cards, t_cards = timed(model, cards, 32, device)
    question = "canh chua cá lóc cho 4 người"
    for _ in range(3):
        model.encode([question])
    start = time.time()
    for _ in range(20):
        model.encode([question])
    t_query = (time.time() - start) / 20

    result = {
        "device": device, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
        "torch": torch.__version__, "model": MODEL, "dim": int(v_names.shape[1]),
        "model_load_s": round(load_s, 1),
        "names": {"n": len(names), "seconds": round(t_names, 2), "ms_each": round(t_names / len(names) * 1000, 2)},
        "cards": {"n": len(cards), "seconds": round(t_cards, 2), "ms_each": round(t_cards / len(cards) * 1000, 2),
                  "median_chars": int(np.median([len(c) for c in cards]))},
        "single_query_ms": round(t_query * 1000, 1),
    }
    if device == "cuda":
        result["vram_peak_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
        result["estimate_all_chunks_s"] = round(t_cards + t_names / len(names) * sum(len(r["ingredients"]) for r in recipes), 1)
        # fp16 (GPU) so với fp32 (CPU) trên 150 tên + 50 thẻ
        rng = np.random.default_rng(0)
        sample = [names[i] for i in rng.choice(len(names), 150, replace=False)] + \
                 [cards[i] for i in rng.choice(len(cards), 50, replace=False)]
        gpu_vec = model.encode(sample, batch_size=32, normalize_embeddings=True)
        del model
        torch.cuda.empty_cache()
        cpu_vec = SentenceTransformer(MODEL, device="cpu").encode(sample, batch_size=32, normalize_embeddings=True)
        cosine = (gpu_vec * cpu_vec).sum(1)
        result["fp16_vs_fp32_cosine_min"] = round(float(cosine.min()), 5)
        result["fp16_vs_fp32_cosine_mean"] = round(float(np.minimum(cosine, 1.0).mean()), 5)
    (PROC / f"bench_embedding_{device}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
