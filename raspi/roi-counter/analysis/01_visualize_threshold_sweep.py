import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# ── params ──────────────────────────────────────────────────────────────────
SWEEP_CSV = "data/outputs/exp1_2788_fixed/sweep_20260621_191909/results.csv"
# ────────────────────────────────────────────────────────────────────────────


def main() -> None:
    csv_path = Path(SWEEP_CSV)
    if not csv_path.exists():
        print(f"[ERROR] file not found: {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    out_dir = csv_path.parent

    if df["count_error"].isna().all():
        print("[WARN] count_error is all NaN (no GT file). Visualizing elapsed_ms only.")

    # ── heatmap: Count Error ───────────────────────────────────────────────
    if not df["count_error"].isna().all():
        pivot = df.pivot(index="s_low", columns="s_high", values="count_error")
        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(pivot, annot=True, fmt=".0f", cmap="YlOrRd_r", ax=ax)
        ax.set_title("Count Error (lower is better)")
        ax.set_xlabel("S_HIGH")
        ax.set_ylabel("S_LOW")
        fig.tight_layout()
        fig.savefig(out_dir / "heatmap_count_error.png", dpi=150)
        plt.close(fig)
        print(f"saved: {out_dir / 'heatmap_count_error.png'}")

        # ── line: S_LOW ───────────────────────────────────────────────────
        mean_by_slow = df.groupby("s_low")["count_error"].mean()
        fig, ax = plt.subplots()
        ax.plot(mean_by_slow.index, mean_by_slow.values, marker="o")
        ax.set_title("S_LOW vs Count Error (mean over S_HIGH)")
        ax.set_xlabel("S_LOW")
        ax.set_ylabel("Count Error (mean)")
        fig.tight_layout()
        fig.savefig(out_dir / "line_s_low.png", dpi=150)
        plt.close(fig)
        print(f"saved: {out_dir / 'line_s_low.png'}")

        # ── line: S_HIGH ──────────────────────────────────────────────────
        mean_by_shigh = df.groupby("s_high")["count_error"].mean()
        fig, ax = plt.subplots()
        ax.plot(mean_by_shigh.index, mean_by_shigh.values, marker="o")
        ax.set_title("S_HIGH vs Count Error (mean over S_LOW)")
        ax.set_xlabel("S_HIGH")
        ax.set_ylabel("Count Error (mean)")
        fig.tight_layout()
        fig.savefig(out_dir / "line_s_high.png", dpi=150)
        plt.close(fig)
        print(f"saved: {out_dir / 'line_s_high.png'}")

    # ── heatmap: elapsed_ms ────────────────────────────────────────────────
    pivot_t = df.pivot(index="s_low", columns="s_high", values="elapsed_ms")
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(pivot_t, annot=True, fmt=".0f", cmap="Blues", ax=ax)
    ax.set_title("elapsed_ms")
    ax.set_xlabel("S_HIGH")
    ax.set_ylabel("S_LOW")
    fig.tight_layout()
    fig.savefig(out_dir / "heatmap_elapsed_ms.png", dpi=150)
    plt.close(fig)
    print(f"saved: {out_dir / 'heatmap_elapsed_ms.png'}")


if __name__ == "__main__":
    main()
