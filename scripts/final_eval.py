"""Model gate: one single run on test, LightGBM vs the 3 baselines.

Reads the model and tau from weights/model_metadata.json (chosen on val),
scores LightGBM and popularity / personal_freq / TIFU-KNN on test, and
applies the gate:

    PASS  if LightGBM Recall@15 >= best baseline Recall@15
    FAIL  otherwise -> record it as a negative result, do not tune on test

Writes <data-dir>/final_test.json. Refuses to run again once that file
exists (or the older data/processed/final_test.json), so test is looked
at only once.

Run:
    python -m scripts.final_eval
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb

from scripts import baselines
from scripts.data_prep import OUT_DIR, RAW_DIR
from scripts.select_threshold import calibration_stats, f1_at_tau, ranked
from scripts.train_lgbm import WEIGHTS_DIR, load_split, rank_top, to_matrix

RESULT_NAME = "final_test.json"
# Where the first (and only) test run was written before --data-dir was used.
LEGACY_RESULT = OUT_DIR / RESULT_NAME


def check_not_run(*paths: Path) -> None:
    """Stop if test has already been scored: any of the result files exists."""
    for path in paths:
        if path.exists():
            raise SystemExit(f"{path} already exists: test has been used once. Read it instead.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed_tt3"))
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args()

    result = args.data_dir / RESULT_NAME
    check_not_run(result, LEGACY_RESULT)

    meta = json.loads((WEIGHTS_DIR / "model_metadata.json").read_text(encoding="utf-8"))
    cols, tau = meta["feature_columns"], meta["tau"]
    model = lgb.Booster(model_file=str(WEIGHTS_DIR / meta["model_file"]))

    test, truth = load_split(args.data_dir, "test")
    p = model.predict(to_matrix(test, cols))
    targets = truth.select(baselines.KEYS).unique()
    results = {"lightgbm": baselines.evaluate(rank_top(test, p), truth, targets)}
    lgbm_tau = f1_at_tau(ranked(test, p), truth, tau)
    calib = calibration_stats(p, test["label"].to_numpy())

    n_users = meta["data"]["n_users"]
    print("running baselines on test...", flush=True)
    base = baselines.run(args.raw_dir, n_users, splits=("test",))["test"]
    results.update(base)

    best_name = max(base, key=lambda n: base[n]["recall@15"])
    best = base[best_name]["recall@15"]
    mine = results["lightgbm"]["recall@15"]
    verdict = "PASS" if mine >= best else "FAIL"

    print(f"{'method':<14}" + "".join(f"{m:>14}" for m in baselines.METRICS))
    for name, m in results.items():
        print(f"{name:<14}" + "".join(f"{m[k]:>14.4f}" for k in baselines.METRICS))
    print(f"LightGBM at tau={tau}: {lgbm_tau}")
    print(f"calibration on test: {calib}")
    print(f"gate: LightGBM recall@15 {mine} vs best baseline {best_name} {best} -> {verdict}")

    result.write_text(
        json.dumps(
            {
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "model_file": meta["model_file"],
                "tau": tau,
                "n_users": n_users,
                "results": results,
                "lightgbm_at_tau": lgbm_tau,
                "calibration_test": calib,
                "gate": {"metric": "recall@15", "lightgbm": mine, "best_baseline": best_name,
                         "best_baseline_value": best, "verdict": verdict},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved {result}")


if __name__ == "__main__":
    main()
