#!/usr/bin/env python3
"""Histogram of per-instance output-token savings from caveman vs baseline.

Savings% = 100 * (baseline_tokens - caveman_tokens) / baseline_tokens
Positive bars = caveman used fewer tokens.
Negative bars = caveman used MORE tokens.

Usage: python3 scripts/render_token_savings_histogram.py [out.png]
"""
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
EXP_CSV = ROOT / "data/experiments.csv"


def main():
    out_name = sys.argv[1] if len(sys.argv) > 1 else "token_savings_histogram.png"
    out_path = ROOT / out_name

    rows = [r for r in csv.DictReader(EXP_CSV.open())
            if r["notes"].startswith("pro pilot")]
    pairs = {}
    for r in rows:
        pairs.setdefault(r["instance_id"], {})[r["condition"]] = r

    savings = []
    for iid, d in pairs.items():
        if "baseline" not in d or "caveman-ultra" not in d:
            continue
        bt = int(d["baseline"]["output_tokens"])
        ct = int(d["caveman-ultra"]["output_tokens"])
        if bt == 0:
            continue
        savings.append(100.0 * (bt - ct) / bt)

    n = len(savings)
    bins = np.arange(-110, 81, 10)

    fig, ax = plt.subplots(figsize=(11, 5))
    counts, edges, patches = ax.hist(savings, bins=bins, edgecolor="white", linewidth=0.8)

    # colour bars by sign
    for patch, left_edge in zip(patches, edges[:-1]):
        if left_edge >= 0:
            patch.set_facecolor("#2ea043")  # green — caveman saved
        else:
            patch.set_facecolor("#d7383f")  # red — caveman used more

    median = float(np.median(savings))
    mean = float(np.mean(savings))

    # shade background: red zone (caveman used more) and green zone (caveman saved)
    ax.axvspan(-200, 0, facecolor="#d7383f", alpha=0.06, zorder=0)
    ax.axvspan(0, 200, facecolor="#2ea043", alpha=0.06, zorder=0)

    # hard divider at 0
    ax.axvline(0, color="#111", linestyle="-", linewidth=2.2, zorder=3)

    ax.axvline(median, color="#222", linestyle="--", linewidth=1.2,
               label=f"median = {median:+.1f}%", zorder=2)
    ax.axvline(mean, color="#222", linestyle=":", linewidth=1.2,
               label=f"mean = {mean:+.1f}%", zorder=2)

    # give extra headroom so zone labels don't overlap bars
    ax.set_ylim(0, max(counts) * 1.35)
    ymax_top = ax.get_ylim()[1]
    ax.text(-80, ymax_top * 0.93, "CAVEMAN USED MORE TOKENS",
            ha="center", va="top", fontsize=10, fontweight="bold",
            color="#a5232a")
    ax.text(50, ymax_top * 0.93, "CAVEMAN SAVED TOKENS",
            ha="center", va="top", fontsize=10, fontweight="bold",
            color="#1f7a33")

    ax.set_xlabel("Token savings per instance (%)  ← caveman used more | caveman used fewer →")
    ax.set_ylabel("Number of instances")
    ax.set_title(f"Per-instance output-token savings: caveman vs baseline  (n = {n})")
    ax.set_xticks(bins)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", frameon=False)

    # summary annotation
    pos = sum(1 for s in savings if s > 0)
    neg = sum(1 for s in savings if s < 0)
    ax.text(0.99, 0.95,
            f"caveman saved tokens: {pos}/{n} ({100*pos/n:.0f}%)\n"
            f"caveman used more:    {neg}/{n} ({100*neg/n:.0f}%)",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=9, family="monospace",
            bbox=dict(facecolor="white", edgecolor="#ccc", boxstyle="round,pad=0.4"))

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Wrote {out_path}  (n={n}, median={median:+.1f}%, mean={mean:+.1f}%)")


if __name__ == "__main__":
    main()
