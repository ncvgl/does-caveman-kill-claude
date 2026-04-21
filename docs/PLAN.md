# Caveman vs. Baseline on SWE-bench Pro — Experiment Plan

## Context and goal

**Question:** does the [caveman](https://github.com/JuliusBrussee/caveman) prompt skill — an ultra-compressed output style — degrade Claude Haiku 4.5's code-correctness on long-horizon software engineering tasks?

**Why now:** a prior pilot on SWE-bench Verified (10 tasks × 2 conditions, archived in `archive/swe_bench_verified_pilot_2026-04-20/`) suggested compression didn't hurt resolve rate at small n but couldn't distinguish noise from real regression. This run scales to SWE-bench Pro (ScaleAI, 101 hand-picked instances) which is harder and multi-language — better resolution for detecting correctness impact.

**Design:** for each of 101 instances, run the same agent twice — once with vanilla Haiku 4.5 (baseline), once with `docs/caveman_ultra_system.md` appended via `--append-system-prompt` (caveman-ultra). Identical user prompt in both. 202 runs total. Compare resolve rate, output tokens, cost.

**Expected wall-time:** 3–4 h at parallelism=4. **Expected cost:** ~$40 (avg $0.20/run × 202; budget cap $2/run).

## Current state (what's done)

1. **Pipeline is built and tested end-to-end** on the first instance (`instance_navidrome__navidrome-de90152a...`). Both conditions resolved=True. See `data/experiments.csv` — 2 backfilled rows.
2. **Pro harness vendored** at `scripts/pro_harness/` (a local copy of `scaleapi/SWE-bench_Pro-os`, patched at `swe_bench_pro_eval.py:381–394` to skip Hub pull if image is already cached locally — avoids burning the 100/6h anonymous Docker Hub rate limit).
3. **`scripts/run_one.sh`** does per-(instance, condition) orchestration: clone repo → run `before_repo_set_cmd` → snapshot as setup_commit → call Claude → `git diff setup_commit HEAD` → build Pro predictions.json → invoke vendored harness → shim Pro output → append row to CSV.
4. **`scripts/log_experiment.py`** appends CSV rows under `fcntl.LOCK_EX` — safe for parallel writers.
5. **10 batch files** persisted at `data/batches/caveman_batch_01.txt` through `caveman_batch_10.txt` (each has 10–11 instance IDs, one per line).
6. **Docker Desktop** reconfigured to 12 GB RAM, 8 CPUs, 128 GB VM disk.

## What's NOT done (the task list)

Recreate these 11 tasks in the fresh session, in this order:

| # | Subject | Source file |
|---|---|---|
| 1  | Batch 1: run instances 1–10 (20 runs)  | `data/batches/caveman_batch_01.txt` |
| 2  | Batch 2: run instances 11–20 (20 runs) | `data/batches/caveman_batch_02.txt` |
| 3  | Batch 3: run instances 21–30 (20 runs) | `data/batches/caveman_batch_03.txt` |
| 4  | Batch 4: run instances 31–40 (20 runs) | `data/batches/caveman_batch_04.txt` |
| 5  | Batch 5: run instances 41–50 (20 runs) | `data/batches/caveman_batch_05.txt` |
| 6  | Batch 6: run instances 51–60 (20 runs) | `data/batches/caveman_batch_06.txt` |
| 7  | Batch 7: run instances 61–70 (20 runs) | `data/batches/caveman_batch_07.txt` |
| 8  | Batch 8: run instances 71–80 (20 runs) | `data/batches/caveman_batch_08.txt` |
| 9  | Batch 9: run instances 81–90 (20 runs) | `data/batches/caveman_batch_09.txt` |
| 10 | Batch 10: run instances 91–101 (22 runs, 11 instances) | `data/batches/caveman_batch_10.txt` |
| 11 | Retry sweep at parallelism 2 | (dynamic — read missing pairs from CSV) |

## How to execute (orchestrator instructions)

The **main Claude Code agent is the orchestrator** — no shell script drives the loop. Pattern:

1. **Delegate each batch to its own subagent** (one subagent per task). Subagent runs its 10–11 instances serially: for each, `./scripts/run_one.sh <iid> baseline` followed by `./scripts/run_one.sh <iid> caveman-ultra`. Skip any (iid, cond) pair already logged in `data/experiments.csv` with `notes` starting `"pro pilot"`.
2. **Run 4 subagents concurrently.** As each completes, launch the next pending batch. This gives parallelism of 4 Claude `-p` sessions (one per subagent) and 4 concurrent Docker containers.
3. **After each batch's 20–22 runs finish,** the subagent runs `docker image rm jefzda/sweap-images:<tag>` for each of its ~10 tags (fail-silent `|| true` — in-use images by other batches will refuse removal and that's fine). Keeps peak disk manageable (~80–110 GB across 4 concurrent batches).
4. **Retry sweep:** once batches 1–10 complete, read `data/experiments.csv` and diff against the 101 instance_ids × 2 conditions = 202 expected pairs. For each missing pair, spawn a subagent that runs that single (iid, cond). Parallelism = 2. Stop when no misses remain (or user decides to give up on persistent failures).

### Subagent prompt template

Each batch-subagent gets a prompt like:

> You're running one batch of a caveman-vs-baseline experiment on SWE-bench Pro. Project root: `/Users/mugen/Codebase/caveman`.
>
> Batch file: `data/batches/caveman_batch_NN.txt` — each line is one `instance_id`.
>
> For every instance in the file, do both conditions in order:
> 1. Skip if CSV already has this (instance_id, condition): `python -c "import csv; print(any(r['instance_id']=='IID' and r['condition']=='COND' and r['notes'].startswith('pro pilot') for r in csv.DictReader(open('data/experiments.csv'))))"`
> 2. Otherwise: `cd /Users/mugen/Codebase/caveman && ./scripts/run_one.sh <instance_id> baseline` — read the last 10 lines of output, extract the `[run_one] DONE: ...` line.
> 3. Same for `caveman-ultra`.
>
> Do NOT parallelize within this subagent — 4 of you run concurrently at the top level.
>
> If a Docker Hub `toomanyrequests` error appears, STOP IMMEDIATELY and report — don't keep hammering.
>
> After all 10–11 instances complete, run `docker image rm jefzda/sweap-images:<tag> 2>/dev/null || true` for each of the batch's dockerhub tags. Look them up via:
> `awk -F, -v iid="<iid>" '$2==iid {print $NF}' data/swe_pro_full.csv` (the `dockerhub_tag` column is the last one).
>
> Report back in under 300 words:
> - n_runs_attempted, n_succeeded, n_failed, n_skipped
> - one-line per failure with the iid+condition+reason
> - aggregate resolved=True count

## Key files

- `scripts/run_one.sh` — per-run orchestration (don't edit casually)
- `scripts/log_experiment.py` — CSV logger with fcntl locking
- `scripts/pro_harness/swe_bench_pro_eval.py` — vendored Pro harness, patched (line 381–394) to skip Hub pull if image cached
- `data/experiments.csv` — results, 31-col schema (currently 2 rows, will grow to 203)
- `data/swe_pro_full.csv` — 731-row materialized Pro dataset (columns include `dockerhub_tag`, `fail_to_pass`, `pass_to_pass`, `before_repo_set_cmd`, `problem_statement`, `requirements`, `interface`)
- `data/batches/caveman_batch_{01..10}.txt` — the 10 batch instance-ID lists
- `swe-bench-pro-public/100_instances.csv` — the canonical 101-instance list (difficulty ranks 100–200 from the full dataset)
- `docs/caveman_ultra_system.md` — upstream caveman SKILL.md + a 3-line ACTIVATION footer. This is what `--append-system-prompt` sees in caveman-ultra runs.
- `archive/swe_bench_verified_pilot_2026-04-20/` — prior Verified-era pilot (experiments.csv, scripts snapshot, sessions, patches, logs). Read-only reference.

## Known caveats (document; don't try to fix)

1. **Caveman-ultra input asymmetry.** `docs/caveman_ultra_system.md` is ~69 lines and includes examples (React/useMemo, SQL pooling, wenyan-classical Chinese, etc.) that become input tokens only for caveman. Baseline doesn't see them. The ACTIVATION footer also adds instruction-following pressure. This is the "caveman as deployed" comparison — honest for the real-world question but not a pure output-compression A/B. Note in writeup.
2. **No wall-clock timeout.** `claude -p` has no `--max-turns` or timeout flag; only `--max-budget-usd 2` stops a runaway run. Expected $0.20 average; theoretical $2 × 202 = $404 if every run hit the cap (won't happen). Each Claude call is expected 2–5 min; a stuck run will burn up to $2 then stop.
3. **Git diff captures anything the agent commits, including scratch files.** If an agent writes e.g. `/tmp/test_mrt.txt` inside the repo dir, it lands in the patch. Low-priority audit job after the run.
4. **Docker Hub anonymous cap of 100/6h.** Our local patch prevents re-pulls within a session, so 100 unique images = 100 pulls — exactly at the cap. If any pull fails, the retry sweep may stall until the 6h window rolls over. User chose not to `docker login` (which would bump to 200/6h).
5. **SWE-bench Pro's grader is fully deterministic** (no LLM-as-judge): per-instance `run_scripts/<iid>/parser.py` converts raw test output into `{name, status}` and resolve = all FAIL_TO_PASS pass ∧ all PASS_TO_PASS pass. The F2P test file IS pre-applied to the agent's workdir via `before_repo_set_cmd` — agent can read it. That's a Pro design choice, not a leak; we tell the agent "failing tests are pre-applied; don't modify them."

## After the run

- Count resolved per condition from `data/experiments.csv`.
- Pivot: `condition × resolved`, plus per-instance (baseline, caveman-ultra) pairs.
- Diff the pair of patches where resolved differs (`patches/<iid>__baseline__*.patch` vs `patches/<iid>__caveman-ultra__*.patch`) — look for systematic caveman failure modes (as we found in sympy-13878 in the Verified pilot, where caveman wrote a mathematically incorrect formula).
- Token/cost delta: sum `output_tokens` and `cost_usd` by condition.
- n=101 paired comparisons is still underpowered for small effects but distinguishes no-effect from moderate-regression at 95% CI ± ~10pp.
