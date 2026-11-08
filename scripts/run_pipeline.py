"""Run the whole predictive reorder pipeline from data/raw, in order.

Only one dataset stays on disk: data/processed (train_targets = 3, the
selected configuration). The train_targets = 1 data exists only for the
ablation and tweak table, in a temporary folder removed at the end; its
runs are appended to data/processed/lgbm_runs.jsonl.

The model gate is the last step. final_eval refuses to run when
final_test.json exists, so test is never scored twice.

Run:
    python -m scripts.run_pipeline
"""

import shutil
import subprocess
import sys
from pathlib import Path

from scripts.data_prep import OUT_DIR

ABLATION_DIR = Path("data/processed_tt1")
USERS = "20000"
TWEAKS = {
    "leaves31": ["--num-leaves", "31"],
    "leaves127": ["--num-leaves", "127"],
    "minleaf20": ["--min-data-in-leaf", "20"],
    "minleaf500": ["--min-data-in-leaf", "500"],
}


def step(module: str, *args: str) -> None:
    print(f"\n=== {module} {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, "-m", f"scripts.{module}", *args], check=True)


def main() -> None:
    tt1 = str(ABLATION_DIR)
    out = str(OUT_DIR)
    step("onnx_probe")
    step("data_prep", "--users", USERS, "--train-targets", "1", "--out-dir", tt1)
    step("data_prep", "--users", USERS, "--train-targets", "3", "--out-dir", out)
    step("baselines", "--users", USERS, "--out-dir", out)

    step("train_lgbm", "--versions", "v0,v1,v2,v3,v4", "--data-dir", tt1, "--tag", "ablation")
    for tag, flags in TWEAKS.items():
        step("train_lgbm", "--versions", "v4", "--data-dir", tt1, "--tag", tag, *flags)
    with open(OUT_DIR / "lgbm_runs.jsonl", "a", encoding="utf-8") as f:
        f.write((ABLATION_DIR / "lgbm_runs.jsonl").read_text(encoding="utf-8"))
    shutil.rmtree(ABLATION_DIR)

    step("train_lgbm", "--versions", "v4", "--data-dir", out, "--tag", "tt3_minleaf500",
         "--min-data-in-leaf", "500")
    step("train_lgbm", "--versions", "v4", "--data-dir", out, "--tag", "selected",
         "--save-model", "--inspect", "5")
    step("select_threshold", "--data-dir", out)
    step("eval_topk", "--data-dir", out)
    step("export_onnx", "--data-dir", out)
    step("build_category_stats")
    step("bench_latency")

    if (OUT_DIR / "final_test.json").exists():
        print("\nfinal_test.json exists: test was already used once, not scoring it again.")
    else:
        step("final_eval", "--data-dir", out)


if __name__ == "__main__":
    main()
