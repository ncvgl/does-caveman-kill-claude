# Does Caveman Kill Claude Code Performance?


TLDR; Caveman uses **~14% fewer output tokens**, with **no statistically significant quality degradation** when tested on a hundred agentic coding tasks. 

## Setup
Making LLMs talk like cavemen save output tokens ("why use many token when few token do trick"). 

We tested here whether the [ultra caveman](https://github.com/JuliusBrussee/caveman) system prompt hurts **Claude Code + Haiku 4.5** on [SWE-bench Pro (public)](https://github.com/scaleapi/SWE-bench_Pro-os) ([HF dataset](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro_Public)).

**Setup.** `claude -p --model claude-haiku-4-5`, budget cap $2/run, WebFetch/WebSearch disabled, all other tools ON. Each instance run twice, same user prompt; only one gets a `docs/caveman_ultra_system.md` prompt via `--append-system-prompt`. Grader = SWE-bench Pro's deterministic test runner.

**Instance selection.** Ranked all SWE-bench Pro Public instances by difficulty (% of  models that resolve each) and picked indices **100–200** — the frontier band: hard enough to stress the agent but easy enough that a resolve-rate difference is measurable.

## Results

| | baseline | caveman-ultra | Δ |
|---|---|---|---|
| Resolve rate | **93.5%** (86/92) | **90.2%** (83/92) | −3% |
| Total cost | $38.06 | $33.66 | −12% |
| Avg cost/run | $0.41 | $0.37 | −12% |
| Avg output tokens/run | 15.3 k | 13.2 k | −14% |

Resolved instances: 79 both / 7 baseline-only / 4 caveman-only / 2 neither / 8 experiment errors. 

## Interpretation

- The **14% output-token savings** is far below the ~65% the caveman repo advertises for natural-language chat. Reason: in an agentic coding loop, most tokens go to tool-call JSON, file contents, code edits, and patches — structured output that can't be compressed into caveman-speak. Only the model's narrative/thinking prose gets compressed, and that's a small fraction of total output here.


- Of the 79 instances both conditions resolved, only **3 produced byte-identical patches**. Those 76 divergent pairs agree on **where** to fix (61% touched the exact same file set) but not on **what** to change (43% of pairs have <30% line overlap) so essentially different implementations of the same fix, both passing the tests.


## Files

- `data/experiments.csv` — one row per (instance, condition); 31 columns including resolve outcome, tokens, cost, and pointers to session/patch artifacts.
- `scripts/run_one.sh` — per-(instance, condition) orchestrator: clones repo, runs setup, invokes claude, produces patch, calls grader, logs to CSV.
- `patches/` — unified diffs the agent produced for each run (`<iid>__<cond>__<session>.patch`).
- `sessions/` — full claude JSONL session transcripts (one per run).
