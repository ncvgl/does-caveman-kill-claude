#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pillow"]
# ///
"""Render a mosaic of the 731 SWE-bench Pro public instances ordered by difficulty
(easiest -> hardest). Each cell is split horizontally: top = baseline, bottom =
caveman-ultra. Green = resolved, red = failed, gray = not attempted / experiment
error. Our 101-instance frontier-band appears as a colored stripe around ranks
100-200.

Usage:  python3 scripts/render_caveman_mosaic.py [out.png]
"""
import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RANK_CSV = ROOT / "swe-bench-pro-public/difficulty_computation/difficulty_ranking.csv"
EXP_CSV = ROOT / "data/experiments.csv"

CELL = 24
GAP = 2
COLS = 28  # 28 * 27 = 756 cells >= 731

GREEN = (46, 160, 67)
RED = (215, 58, 73)
GRAY = (180, 180, 180)
BG = (255, 255, 255)


def load_outcomes():
    """Return dict: instance_id -> {'baseline': bool|None, 'caveman-ultra': bool|None}."""
    out = {}
    with EXP_CSV.open() as f:
        for r in csv.DictReader(f):
            if not r["notes"].startswith("pro pilot"):
                continue
            iid = r["instance_id"]
            cond = r["condition"]
            resolved = r["resolved"] == "True"
            out.setdefault(iid, {})[cond] = resolved
    return out


def color_for(resolved):
    if resolved is True:
        return GREEN
    if resolved is False:
        return RED
    return GRAY


def main() -> None:
    out_name = sys.argv[1] if len(sys.argv) > 1 else "caveman_vs_baseline_mosaic.png"
    out_path = ROOT / out_name

    with RANK_CSV.open() as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r["difficulty_rank"]))

    outcomes = load_outcomes()

    n = len(rows)
    cols = COLS
    rows_n = (n + cols - 1) // cols
    width = cols * CELL + (cols + 1) * GAP
    height = rows_n * CELL + (rows_n + 1) * GAP

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    counts = {"baseline_pass": 0, "baseline_fail": 0, "caveman_pass": 0,
              "caveman_fail": 0, "untested": 0}
    half = CELL // 2

    for i, row in enumerate(rows):
        iid = row["instance_id"]
        c = i % cols
        r = i // cols
        x = GAP + c * (CELL + GAP)
        y = GAP + r * (CELL + GAP)

        out = outcomes.get(iid)
        if out is None:
            base_r, cav_r = None, None
            counts["untested"] += 1
        else:
            base_r = out.get("baseline")
            cav_r = out.get("caveman-ultra")
            if base_r is True: counts["baseline_pass"] += 1
            elif base_r is False: counts["baseline_fail"] += 1
            if cav_r is True: counts["caveman_pass"] += 1
            elif cav_r is False: counts["caveman_fail"] += 1

        # top half = baseline, bottom half = caveman-ultra
        draw.rectangle([x, y, x + CELL - 1, y + half - 1], fill=color_for(base_r))
        draw.rectangle([x, y + half, x + CELL - 1, y + CELL - 1], fill=color_for(cav_r))

    img.save(out_path, "PNG")
    print(f"Wrote {out_path}  ({width}x{height}, {n} cells)")
    print(f"  baseline:       pass={counts['baseline_pass']:3d}  fail={counts['baseline_fail']:3d}")
    print(f"  caveman-ultra:  pass={counts['caveman_pass']:3d}  fail={counts['caveman_fail']:3d}")
    print(f"  untested/error: {counts['untested']}")


if __name__ == "__main__":
    main()
