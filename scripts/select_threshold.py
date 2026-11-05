"""Calibration check and threshold (tau) selection on val.

1. Reliability diagram of the selected model's probabilities on val
   (10 equal-width bins) and the expected calibration error (ECE).
   Most probabilities sit in the first bin, so equal-width ECE is also
   reported with 10 equal-count (quantile) bins, next to the Brier score
   and the Brier score of always predicting the base rate.
2. If quantile ECE > ECE_LIMIT, try isotonic regression: fit on half of the val
   users, measure ECE on the other half. Keep it only if it helps; the
   kept mapping is then refit on all of val and stored as thresholds
   (no pickle), so /predict can apply it with np.interp.
3. Sweep tau: recommend the top-15 products whose probability >= tau.
   F1@15(tau) uses precision = hits / products recommended (not / 15),
   since the list is cut by tau. Orders with nothing recommended score 0.
   tau = 0 gives the uncut top-15 under the same definition, to compare.
4. Recall@15 of an oracle that ranks every true candidate first: the
   ceiling of any model limited to the user's purchase history.
5. Write tau and everything /predict needs into weights/model_metadata.json.

Run:
    python -m scripts.select_threshold
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression

from scripts.data_prep import OUT_DIR
from scripts.train_lgbm import KEYS, WEIGHTS_DIR, load_split, machine_info, to_matrix
from src.ml.feature_extractor import FEATURE_SETS

ECE_LIMIT = 0.02
K = 15
TAUS = np.round(np.arange(0.02, 0.61, 0.01), 2)
FIG_DIR = Path("docs/figures")


def reliability(
    p: np.ndarray, y: np.ndarray, bins: int = 10, quantile: bool = False
) -> tuple[pl.DataFrame, float]:
    """Per-bin mean prediction vs observed rate, and ECE (weighted |gap|).

    quantile=True: bins of equal count (by rank of p) instead of equal width.
    """
    if quantile:
        b = np.argsort(np.argsort(p, kind="stable"), kind="stable") * bins // len(p)
    else:
        b = np.minimum((p * bins).astype(int), bins - 1)
    df = (
        pl.DataFrame({"bin": b, "p": p, "y": y})
        .group_by("bin")
        .agg(n=pl.len(), mean_p=pl.col("p").mean(), rate=pl.col("y").mean())
        .sort("bin")
    )
    ece = float(((df["mean_p"] - df["rate"]).abs() * df["n"]).sum() / len(p))
    return df, ece


def calibration_stats(p: np.ndarray, y: np.ndarray) -> dict:
    """ECE (equal-width and quantile bins), Brier, and Brier of the base rate."""
    _, ece_w = reliability(p, y)
    _, ece_q = reliability(p, y, quantile=True)
    return {
        "ece_uniform": round(ece_w, 4),
        "ece_quantile": round(ece_q, 4),
        "brier": round(float(np.mean((p - y) ** 2)), 5),
        "brier_base_rate": round(float(np.mean((y.mean() - y) ** 2)), 5),
    }


def oracle_recall(cand: pl.DataFrame, truth: pl.DataFrame, k: int = K) -> float:
    """Mean Recall@k when every true candidate is ranked first (the ceiling)."""
    found = cand.select(KEYS + ["product_id"]).join(truth, on=KEYS + ["product_id"])
    per = (
        truth.group_by(KEYS).agg(n_true=pl.len())
        .join(found.group_by(KEYS).agg(n_found=pl.len()), on=KEYS, how="left")
        .fill_null(0)
        .with_columns(r=pl.min_horizontal("n_found", pl.lit(k)) / pl.col("n_true"))
    )
    return round(float(per["r"].mean()), 4)


def f1_at_tau(scored: pl.DataFrame, truth: pl.DataFrame, tau: float, k: int = K) -> dict:
    preds = scored.filter((pl.col("rank") <= k) & (pl.col("p") >= tau))
    hits = preds.join(truth, on=KEYS + ["product_id"]).group_by(KEYS).agg(hit=pl.len())
    per = (
        truth.group_by(KEYS).agg(n_true=pl.len())
        .join(preds.group_by(KEYS).agg(n_pred=pl.len()), on=KEYS, how="left")
        .join(hits, on=KEYS, how="left")
        .fill_null(0)
        .with_columns(
            prec=pl.when(pl.col("n_pred") > 0).then(pl.col("hit") / pl.col("n_pred")).otherwise(0.0),
            rec=pl.col("hit") / pl.col("n_true"),
        )
        .with_columns(
            f1=pl.when(pl.col("prec") + pl.col("rec") > 0)
            .then(2 * pl.col("prec") * pl.col("rec") / (pl.col("prec") + pl.col("rec")))
            .otherwise(0.0)
        )
    )
    return {
        "tau": float(tau),
        "f1@15": round(per["f1"].mean(), 4),
        "precision": round(per["prec"].mean(), 4),
        "recall": round(per["rec"].mean(), 4),
        "avg_items": round(per["n_pred"].mean(), 2),
        "empty_orders": round((per["n_pred"] == 0).mean(), 4),
    }


def ranked(df: pl.DataFrame, p: np.ndarray) -> pl.DataFrame:
    return (
        df.select(KEYS + ["product_id"])
        .with_columns(p=pl.Series(p))
        .sort(KEYS + ["p", "product_id"], descending=[False, False, True, False])
        .with_columns(rank=pl.col("product_id").cum_count().over(KEYS))
    )


def plot(curves: dict[str, pl.DataFrame], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", label="hoàn hảo")
    for name, df in curves.items():
        ax.plot(df["mean_p"], df["rate"], marker="o", label=name)
    ax.set_xlabel("Xác suất dự đoán trung bình (theo bin)")
    ax.set_ylabel("Tỉ lệ thực tế được mua")
    ax.set_title("Reliability diagram (val)")
    ax.legend()
    ax.grid(alpha=0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def plot_tau(sweep: list[dict], best_tau: float, path: Path) -> None:
    """F1@15, precision and recall against tau, as in the tau table of the report."""
    taus = [r["tau"] for r in sweep]
    fig, ax = plt.subplots(figsize=(6, 4))
    for key, label in (("f1@15", "F1@15"), ("precision", "Precision"), ("recall", "Recall")):
        ax.plot(taus, [r[key] for r in sweep], label=label)
    ax.axvline(best_tau, linestyle="--", color="grey", label=f"τ = {best_tau}")
    ax.set_xlabel("τ")
    ax.set_title("Đường cong τ (val)")
    ax.legend()
    ax.grid(alpha=0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--model", type=Path, default=WEIGHTS_DIR / "lgbm_v4_selected.txt")
    parser.add_argument("--version", default="v4")
    args = parser.parse_args()

    cols = FEATURE_SETS[args.version]
    model = lgb.Booster(model_file=str(args.model))
    val, truth = load_split(args.data_dir, "val")
    p = model.predict(to_matrix(val, cols))
    y = val["label"].to_numpy()

    raw_curve, _ = reliability(p, y)
    stats = calibration_stats(p, y)
    ece_raw = stats["ece_quantile"]
    print(f"calibration (val): {stats}")
    print(raw_curve)
    curves = {f"LightGBM (ECE {stats['ece_uniform']:.3f})": raw_curve}
    calibration = {"method": "none", **stats}

    if ece_raw > ECE_LIMIT:
        # Fit on half of the users, judge on the other half.
        # user_id parity: deterministic, unlike hashes across polars versions.
        half = (val["user_id"] % 2 == 0).to_numpy()
        iso = IsotonicRegression(out_of_bounds="clip").fit(p[half], y[half])
        _, ece_b_raw = reliability(p[~half], y[~half], quantile=True)
        iso_curve, ece_b_iso = reliability(iso.predict(p[~half]), y[~half], quantile=True)
        print(f"held-out half: ECE raw {ece_b_raw:.4f} -> isotonic {ece_b_iso:.4f}")
        curves[f"isotonic, nửa giữ lại (ECE {ece_b_iso:.3f})"] = iso_curve
        if ece_b_iso < ece_b_raw:
            iso = IsotonicRegression(out_of_bounds="clip").fit(p, y)
            p = iso.predict(p)
            calibration = {
                "method": "isotonic",
                **stats,
                "ece_heldout_raw": round(ece_b_raw, 4),
                "ece_heldout_isotonic": round(ece_b_iso, 4),
                "x": iso.X_thresholds_.round(6).tolist(),
                "y": iso.y_thresholds_.round(6).tolist(),
            }

    fig_path = FIG_DIR / "reliability_val.png"
    plot(curves, fig_path)
    print(f"saved {fig_path}")

    scored = ranked(val, p)
    sweep = [f1_at_tau(scored, truth, t) for t in TAUS]
    best = max(sweep, key=lambda r: (r["f1@15"], -r["tau"]))
    print(f"{'tau':>5} {'f1@15':>7} {'prec':>7} {'recall':>7} {'items':>6} {'empty':>6}")
    for r in sweep[::3] + [best]:
        print(f"{r['tau']:>5.2f} {r['f1@15']:>7.4f} {r['precision']:>7.4f} {r['recall']:>7.4f}"
              f" {r['avg_items']:>6.2f} {r['empty_orders']:>6.3f}")
    print(f"best tau = {best['tau']}")
    plot_tau(sweep, best["tau"], FIG_DIR / "tau_curve_val.png")
    no_tau = f1_at_tau(scored, truth, 0.0)
    oracle = oracle_recall(val, truth)
    print(f"no tau (same F1 definition): {no_tau}")
    print(f"oracle recall@15 on val = {oracle}")

    data_meta_path = args.data_dir / "meta.json"
    data_meta = json.loads(data_meta_path.read_text(encoding="utf-8")) if data_meta_path.exists() else {}
    metadata = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": machine_info(),
        "model_file": args.model.name,
        "feature_version": args.version,
        "feature_columns": cols,
        "top_k": K,
        "tau": best["tau"],
        "tau_selection": {"split": "val", "metric": "f1@15", "grid": [float(TAUS[0]), float(TAUS[-1]), 0.01],
                          "best": best, "no_tau": no_tau},
        "oracle_recall@15_val": oracle,
        "calibration": calibration,
        "split": {
            "method": "leave-last-out per user",
            "test": "order n",
            "val": "order n-1",
            "train": "orders 1..n-2; the last train_targets of them are labels",
            "why": "Instacart has no absolute dates, so a global time cut is impossible",
        },
        "data": {k: data_meta.get(k) for k in ("n_users", "seed", "min_orders", "train_targets",
                                                "max_candidates", "dsp_cap")},
    }
    WEIGHTS_DIR.mkdir(exist_ok=True)
    out = WEIGHTS_DIR / "model_metadata.json"
    out.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.data_dir / "tau_sweep.json").write_text(json.dumps(sweep, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
