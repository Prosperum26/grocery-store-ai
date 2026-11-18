"""ONNX model inference boundary."""

from pathlib import Path

import numpy as np
import onnxruntime as ort
import polars as pl


def to_matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    """float32 matrix, nulls as NaN (missing value), same as training."""
    return df.select(pl.col(cols).cast(pl.Float32)).to_numpy()


class OnnxScorer:
    """Probability of being bought, one row per candidate."""

    def __init__(self, path: Path) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1  # one request, few rows: threads only add latency
        options.log_severity_level = 3  # the converter declares a fixed label shape; harmless
        self._session = ort.InferenceSession(
            str(path), options, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self._session.run(None, {self._input: x})[1][:, 1]
