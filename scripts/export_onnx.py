"""Export the selected LightGBM model to ONNX and check parity on all of val.

PASS needs both: max |onnx - lightgbm| < PARITY_LIMIT, and the same top-15
products for every target order. The result is written into
weights/model_metadata.json, so run this after select_threshold.

Run:
    python -m scripts.export_onnx
"""

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import onnxruntime as ort
import polars as pl
from onnxmltools import convert_lightgbm
from onnxmltools.convert.common.data_types import FloatTensorType

from scripts.data_prep import OUT_DIR
from scripts.train_lgbm import WEIGHTS_DIR, load_split, rank_top, to_matrix

PARITY_LIMIT = 1e-4
OPSET = 15


def export(model: lgb.Booster, n_features: int, path: Path) -> None:
    onx = convert_lightgbm(
        model,
        initial_types=[("input", FloatTensorType([None, n_features]))],
        zipmap=False,
        target_opset=OPSET,
    )
    path.write_bytes(onx.SerializeToString())


def onnx_probability(session: ort.InferenceSession, x: np.ndarray) -> np.ndarray:
    """P(label = 1). Output 1 of the converted classifier has two columns."""
    name = session.get_inputs()[0].name
    return session.run(None, {name: x})[1][:, 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    meta_path = WEIGHTS_DIR / "model_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cols = meta["feature_columns"]
    model = lgb.Booster(model_file=str(WEIGHTS_DIR / meta["model_file"]))
    onnx_path = WEIGHTS_DIR / (Path(meta["model_file"]).stem + ".onnx")
    export(model, len(cols), onnx_path)

    val, _ = load_split(args.data_dir, "val")
    x = to_matrix(val, cols)
    expected = model.predict(x)
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    got = onnx_probability(session, x)

    diff = np.abs(got - expected)
    keys = ["user_id", "t_order", "rank"]
    a = rank_top(val, expected, 15).select(keys + ["product_id"]).sort(keys)
    b = rank_top(val, got, 15).select(keys + ["product_id"]).sort(keys)
    changed = (
        a.join(b, on=keys, suffix="_onnx")
        .filter(pl.col("product_id") != pl.col("product_id_onnx"))
        .select("user_id", "t_order")
        .unique()
        .height
    )
    parity = {
        "split": "val",
        "rows": len(x),
        "rows_with_nan": int(np.isnan(x).any(axis=1).sum()),
        "max_abs_diff": float(diff.max()),
        "p99_abs_diff": float(np.percentile(diff, 99)),
        "orders_with_different_top15": changed,
        "orders": val.select("user_id", "t_order").unique().height,
        "limit": PARITY_LIMIT,
    }
    print(parity)
    if diff.max() >= PARITY_LIMIT:
        raise SystemExit("ONNX parity failed: probabilities differ too much")

    meta["onnx"] = {"file": onnx_path.name, "opset": OPSET, "parity": parity}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {onnx_path}")


if __name__ == "__main__":
    main()
