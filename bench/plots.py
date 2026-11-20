"""CSV → 그래프(bench/results/figures/*.png)."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RES = Path(__file__).resolve().parent / "results"
FIG = RES / "figures"
COL = {"B1": "#9aa5b1", "B2": "#4c78a8", "P": "#e45756"}
METHOD_COL = {"random": "#bab0ac", "market_value": "#4c78a8", "similarity": "#e45756", "hybrid": "#54a24b"}


def _read(name: str) -> list[dict]:
    with (RES / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def latency() -> Path:
    rows = _read("query_summary.csv")
    qs = ["Q1", "Q2", "Q3"]
    fig, ax = plt.subplots(figsize=(7, 4))
    w = 0.26
    for j, cfg in enumerate(("B1", "B2", "P")):
        vals = [float(next(r for r in rows if r["query"] == q and r["config"] == cfg)["median_ms"]) for q in qs]
        bars = ax.bar([i + (j - 1) * w for i in range(3)], vals, w, label=cfg, color=COL[cfg])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.1, f"{v:,.1f}", ha="center", va="bottom", fontsize=7)
    ax.set_yscale("log")
    ax.set_xticks(range(3), ["Q1 season history", "Q2 cohort percentile", "Q3 k-NN (k=10)"])
    ax.set_ylabel("median latency (ms, log scale)")
    ax.set_title("Query latency: B1 (raw, no index) / B2 (raw, indexed) / P (derived tables)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p = FIG / "query_latency.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def backtest() -> Path:
    rows = [r for r in _read("backtest.csv") if r["k"] == "20"]
    agg: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        agg[(r["pos_group"], r["method"])].append(float(r["precision"]))
    pos = ["GK", "DF", "MF", "FW", "ALL"]
    methods = ["random", "market_value", "similarity", "hybrid"]
    fig, ax = plt.subplots(figsize=(8, 4))
    w = 0.2
    for j, m in enumerate(methods):
        vals = []
        for p in pos:
            xs = [x for (pp, mm), v in agg.items() if mm == m and (p == "ALL" or pp == p) for x in v]
            vals.append(sum(xs) / len(xs) if xs else 0)
        bars = ax.bar([i + (j - 1.5) * w for i in range(len(pos))], vals, w, label=m, color=METHOD_COL[m])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.002, f"{v:.2f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(pos)), pos)
    ax.set_ylabel("precision@20 (mean over snapshots x definitions)")
    ax.set_title("Backtest precision@20 by method and position group")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p = FIG / "backtest_precision20.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def refresh() -> Path:
    rows = _read("refresh.csv")
    pick = [("build_player_season(1 season", "build_player_season\n(1 season)"),
            ("build_snapshot(current) run", "build_snapshot\n(current)"),
            ("build_player_season(all", "build_player_season\n(all seasons)")]
    labels, vals = [], []
    for prefix, lab in pick:
        xs = [float(r["value"]) for r in rows if r["unit"] == "s" and r["operation"].startswith(prefix)]
        if xs:
            labels.append(lab)
            vals.append(sorted(xs)[len(xs) // 2])
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, vals, color=["#4c78a8", "#54a24b", "#e45756"][: len(vals)])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}s", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("seconds (median)")
    ax.set_title("Refresh cost of derived tables")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p = FIG / "refresh_cost.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def make_all() -> list[Path]:
    FIG.mkdir(parents=True, exist_ok=True)
    return [latency(), backtest(), refresh()]


if __name__ == "__main__":
    print(make_all())
