#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyarrow", "requests"]
# ///
"""
Rank the 731 SWE-bench Pro public instances from easiest to hardest.

Primary signal: fraction of the 9 evaluated frontier models that resolved each
instance (from traj/<model>/eval_results.json in scaleapi/SWE-bench_Pro-os).

Tiebreakers (for instances where fraction_solved == 0, the "no model solved"
wall): patch LOC + files changed + FAIL_TO_PASS count.

Output: difficulty_ranking.csv sorted easy -> hard.
"""
import csv
import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq
import requests

HERE = Path(__file__).parent
PARQUET_URL = (
    "https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro/"
    "resolve/main/data/test-00000-of-00001.parquet"
)
MODELS = [
    "claude-45sonnet-10132025",
    "claude-4sonnet-10132025",
    "claude-opus-4-1-paper",
    "claude-sonnet-4-paper",
    "gemini-2-5-pro-preview-paper",
    "gpt-4o-paper",
    "gpt-5-250-turns-10132025",
    "gptoss-paper",
    "kimi-k2-instruct-10132025",
]
EVAL_URL = (
    "https://raw.githubusercontent.com/scaleapi/SWE-bench_Pro-os/"
    "main/traj/{model}/eval_results.json"
)


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    print(f"  downloading {url}", file=sys.stderr)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def load_dataset() -> list[dict]:
    cache = HERE / "swe_bench_pro_public.parquet"
    download(PARQUET_URL, cache)
    table = pq.read_table(cache)
    return table.to_pylist()


def load_eval_results() -> dict[str, dict[str, bool]]:
    cache_dir = HERE / "eval_results"
    cache_dir.mkdir(exist_ok=True)
    out: dict[str, dict[str, bool]] = {}
    for model in MODELS:
        dest = cache_dir / f"{model}.json"
        download(EVAL_URL.format(model=model), dest)
        data = json.loads(dest.read_text())
        out[model] = {k: bool(v) for k, v in data.items()}
    return out


# --- intrinsic features ---------------------------------------------------

DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/", re.MULTILINE)


def patch_stats(patch: str) -> tuple[int, int]:
    """Return (added+deleted LOC, files changed) for a unified diff."""
    if not patch:
        return 0, 0
    added = sum(
        1
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    deleted = sum(
        1
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    files = len(DIFF_FILE_RE.findall(patch))
    return added + deleted, files


def fail_to_pass_count(value) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return len(parsed)
        except json.JSONDecodeError:
            pass
        return len([x for x in s.splitlines() if x.strip()])
    return 0


# --- main -----------------------------------------------------------------


def main() -> None:
    print("Loading dataset...", file=sys.stderr)
    rows = load_dataset()
    public_ids = {r["instance_id"] for r in rows}
    print(f"  dataset: {len(rows)} instances", file=sys.stderr)

    print("Loading eval results...", file=sys.stderr)
    evals = load_eval_results()
    for model, data in evals.items():
        overlap = len(set(data) & public_ids)
        print(
            f"  {model}: {len(data)} entries, {overlap} match public IDs",
            file=sys.stderr,
        )

    print("Scoring instances...", file=sys.stderr)
    sonnet45 = evals["claude-45sonnet-10132025"]
    opus41 = evals["claude-opus-4-1-paper"]
    out_rows: list[dict] = []
    for r in rows:
        iid = r["instance_id"]
        attempts: list[bool] = []
        for model_data in evals.values():
            if iid in model_data:
                attempts.append(model_data[iid])
        solved = sum(attempts)
        n = len(attempts)
        fraction = solved / n if n else float("nan")

        loc, files = patch_stats(r.get("patch") or "")
        f2p_n = fail_to_pass_count(r.get("fail_to_pass"))
        ps = r.get("problem_statement") or ""

        out_rows.append(
            {
                "instance_id": iid,
                "repo": r.get("repo"),
                "language": r.get("repo_language"),
                "fraction_solved": fraction,
                "n_solved": solved,
                "n_models_attempted": n,
                "claude_45sonnet_passed": sonnet45.get(iid, ""),
                "claude_opus_4_1_passed": opus41.get(iid, ""),
                "patch_loc": loc,
                "files_changed": files,
                "fail_to_pass_count": f2p_n,
                "problem_statement_len": len(ps),
            }
        )

    # Sort: easiest (highest fraction_solved) first.
    # For the hardest bucket (fraction_solved == 0), fall back to intrinsic
    # features to order the "nobody solved it" wall.
    def sort_key(row: dict) -> tuple:
        # primary: higher fraction_solved first (easier)
        # tiebreakers: smaller patch_loc, fewer files, fewer f2p tests (easier)
        fs = row["fraction_solved"]
        bucket = 1 if fs == 0 else 0
        return (
            bucket,
            -fs,
            row["patch_loc"],
            row["files_changed"],
            row["fail_to_pass_count"],
        )

    out_rows.sort(key=sort_key)
    for rank, row in enumerate(out_rows, start=1):
        row["difficulty_rank"] = rank

    out_path = HERE / "difficulty_ranking.csv"
    fields = [
        "difficulty_rank",
        "instance_id",
        "repo",
        "language",
        "fraction_solved",
        "n_solved",
        "n_models_attempted",
        "claude_45sonnet_passed",
        "claude_opus_4_1_passed",
        "patch_loc",
        "files_changed",
        "fail_to_pass_count",
        "problem_statement_len",
    ]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {out_path} ({len(out_rows)} rows)", file=sys.stderr)

    # Summary
    unsolved = sum(1 for r in out_rows if r["fraction_solved"] == 0)
    fully_solved = sum(1 for r in out_rows if r["fraction_solved"] == 1.0)
    print(
        f"Summary: {fully_solved} solved by all models, "
        f"{unsolved} solved by none",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
