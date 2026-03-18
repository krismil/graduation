import sys
from pathlib import Path
import os

if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = str(Path(".mplconfig").resolve())

sys.path.insert(0, "backend")
from app.services.legacy_adapter import compare_legacy_strategies

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCENARIOS = ["fitSNR", "fit5TASK", "fit15TASK"]
STRATEGIES = ["semslice", "netslice", "random"]
VECTOR = [0.2, 0.3, 0.5, 0.6, 0.8, 0.6]


def main():
    results = {}
    for scenario in SCENARIOS:
        out = compare_legacy_strategies(scenario, VECTOR, "paper_sim")
        results[scenario] = {item["strategy"]: item for item in out["comparisons"]}

    avg_delay = np.array([[results[s][st]["avg_delay_ms"] for s in SCENARIOS] for st in STRATEGIES], dtype=float)
    avg_ss = np.array([[results[s][st]["avg_ss"] for s in SCENARIOS] for st in STRATEGIES], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), dpi=160)
    bar_w = 0.22
    x = np.arange(len(SCENARIOS))
    colors = ["#0f766e", "#0ea5e9", "#f59e0b"]

    for i, st in enumerate(STRATEGIES):
        axes[0].bar(x + (i - 1) * bar_w, avg_delay[i], width=bar_w, label=st, color=colors[i])
    axes[0].set_title("Average Delay Comparison")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(SCENARIOS)
    axes[0].set_ylabel("Delay (ms)")
    axes[0].grid(axis="y", linestyle="--", alpha=0.3)

    for i, st in enumerate(STRATEGIES):
        axes[1].bar(x + (i - 1) * bar_w, avg_ss[i], width=bar_w, label=st, color=colors[i])
    axes[1].set_title("Average SS Comparison")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(SCENARIOS)
    axes[1].set_ylabel("SS")
    axes[1].set_ylim(0.55, 0.95)
    axes[1].grid(axis="y", linestyle="--", alpha=0.3)

    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
    fig.suptitle("SemSlice / NetSlice / Random (paper_sim mode)")
    fig.tight_layout(rect=[0, 0.08, 1, 0.93])

    out_dir = Path("docs/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_dir / "algorithm_comparison.png"), bbox_inches="tight")

    csv_lines = ["scenario,strategy,avg_delay_ms,avg_ss,avg_s_se"]
    for s in SCENARIOS:
        for st in STRATEGIES:
            item = results[s][st]
            csv_lines.append(f"{s},{st},{item['avg_delay_ms']:.6f},{item['avg_ss']:.6f},{item['avg_s_se']:.6f}")
    (out_dir / "algorithm_comparison.csv").write_text("\n".join(csv_lines), encoding="utf-8")

    print("saved:", out_dir / "algorithm_comparison.png")


if __name__ == "__main__":
    main()
