#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pillow"]
# ///
"""
Render a mosaic of the 731 SWE-bench Pro public instances ordered by
difficulty (easiest -> hardest, left-to-right, top-to-bottom).

Usage:  uv run --script render_mosaic.py <csv_column> <output_filename>
Example: uv run --script render_mosaic.py claude_opus_4_1_passed opus41_mosaic.png

Green  = model passed
Red    = model failed
Gray   = not attempted
"""
import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
CSV_PATH = HERE / "difficulty_ranking.csv"

CELL = 24
GAP = 2
COLS = 28  # 28 * 27 = 756 cells > 731

GREEN = (46, 160, 67)
RED = (215, 58, 73)
GRAY = (180, 180, 180)
BG = (255, 255, 255)


def main() -> None:
    column = sys.argv[1] if len(sys.argv) > 1 else "claude_45sonnet_passed"
    out_name = sys.argv[2] if len(sys.argv) > 2 else "sonnet45_mosaic.png"
    out_path = HERE / out_name

    with CSV_PATH.open() as f:
        rows = list(csv.DictReader(f))

    n = len(rows)
    cols = COLS
    rows_n = (n + cols - 1) // cols
    width = cols * CELL + (cols + 1) * GAP
    height = rows_n * CELL + (rows_n + 1) * GAP

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    counts = {"True": 0, "False": 0, "": 0}
    for i, row in enumerate(rows):
        c = i % cols
        r = i // cols
        x = GAP + c * (CELL + GAP)
        y = GAP + r * (CELL + GAP)
        passed = row[column]
        counts[passed] = counts.get(passed, 0) + 1
        if passed == "True":
            color = GREEN
        elif passed == "False":
            color = RED
        else:
            color = GRAY
        draw.rectangle([x, y, x + CELL - 1, y + CELL - 1], fill=color)

    img.save(out_path, "PNG")
    print(f"Wrote {out_path}  ({width}x{height}, {n} cells)")
    print(
        f"  passed={counts.get('True', 0)} "
        f"failed={counts.get('False', 0)} "
        f"not_attempted={counts.get('', 0)}"
    )


if __name__ == "__main__":
    main()
