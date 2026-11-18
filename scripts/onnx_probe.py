"""Check that a LightGBM binary model survives ONNX conversion.

Trains two toy models, one with numeric features only and one with a
categorical column, converts each with onnxmltools, runs it with
onnxruntime and compares probabilities with LightGBM's own.

Run:
    python -m scripts.onnx_probe
"""

import numpy as np
import lightgbm as lgb
import onnxruntime as ort
from onnxmltools import convert_lightgbm
from onnxmltools.convert.common.data_types import FloatTensorType

N, SEED = 5000, 0


def toy(categorical: bool) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    x = rng.normal(size=(N, 4)).astype(np.float32)
    x[rng.random(N) < 0.2, 1] = np.nan  # like streak_ratio
    logit = x[:, 0] - 0.5 * np.nan_to_num(x[:, 1])
    if categorical:
        x[:, 3] = rng.integers(0, 7, N)  # like t_dow
        logit += np.where(x[:, 3] >= 5, 1.0, -0.3)
    y = (rng.random(N) < 1 / (1 + np.exp(-logit))).astype(int)
    return x, y


def probe(categorical: bool) -> str:
    x, y = toy(categorical)
    model = lgb.LGBMClassifier(n_estimators=50, num_leaves=15, verbose=-1)
    model.fit(x, y, categorical_feature=[3] if categorical else "auto")
    expected = model.predict_proba(x)[:, 1]
    try:
        onx = convert_lightgbm(
            model,
            initial_types=[("input", FloatTensorType([None, x.shape[1]]))],
            zipmap=False,
            target_opset=15,
        )
        sess = ort.InferenceSession(onx.SerializeToString(), providers=["CPUExecutionProvider"])
        got = sess.run(None, {"input": x})[1][:, 1]
    except Exception as e:  # report, do not crash: this is a probe
        return f"FAIL conversion: {type(e).__name__}: {e}"
    diff = float(np.abs(got - expected).max())
    status = "OK" if diff < 1e-5 else "MISMATCH"
    return f"{status} max |onnx - lgbm| = {diff:.2e}"


def main() -> None:
    for categorical in (False, True):
        name = "with categorical" if categorical else "numeric only"
        print(f"{name:<18} {probe(categorical)}")


if __name__ == "__main__":
    main()
