#!/usr/bin/env bash
# Usage: ./run_one.sh <instance_id> <baseline|caveman-ultra>
# Target: SWE-bench Pro (ScaleAI/SWE-bench_Pro) via scaleapi/SWE-bench_Pro-os harness.
set -euo pipefail

INSTANCE_ID="${1:?need instance_id}"
CONDITION="${2:?need condition (baseline|caveman-ultra)}"

case "$CONDITION" in
  baseline|caveman-ultra) ;;
  *) echo "Unknown condition: $CONDITION" >&2; exit 2;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source venv/bin/activate

PRO_REPO="$ROOT/scripts/pro_harness"         # vendored scaleapi/SWE-bench_Pro-os (local-patched: skip Hub pull if image cached)
PRO_CSV="$ROOT/data/swe_pro_full.csv"        # materialized from the HF parquet
SYS_PROMPT="$ROOT/docs/caveman_ultra_system.md"

[[ -d "$PRO_REPO" ]]  || { echo "Missing $PRO_REPO — git clone scaleapi/SWE-bench_Pro-os there"; exit 2; }
[[ -f "$PRO_CSV" ]]   || { echo "Missing $PRO_CSV"; exit 2; }

# --- 1. load task metadata from Pro CSV (Python: field parsing is non-trivial) ---
eval "$(python - <<PY
import pandas as pd, shlex
df = pd.read_csv('$PRO_CSV')
r = df[df['instance_id'] == '$INSTANCE_ID']
assert len(r) == 1, f'instance $INSTANCE_ID not found (n={len(r)})'
r = r.iloc[0]
print(f"REPO={shlex.quote(r['repo'])}")
print(f"BASE_COMMIT={shlex.quote(r['base_commit'])}")
print(f"BEFORE_CMD={shlex.quote(r['before_repo_set_cmd'].strip())}")
print(f"PROBLEM_STATEMENT={shlex.quote(r['problem_statement'])}")
print(f"REQUIREMENTS={shlex.quote(r['requirements'])}")
print(f"INTERFACE={shlex.quote(r['interface'])}")
print(f"LANGUAGE={shlex.quote(r['repo_language'])}")
print(f"DOCKERHUB_TAG={shlex.quote(r['dockerhub_tag'])}")
PY
)"

echo "[run_one] $INSTANCE_ID ($LANGUAGE) / $CONDITION / repo=$REPO"

# --- 2. prepare workdir: clone, then execute Pro's before_repo_set_cmd (resets + checkout test file) ---
WORKREPO="$ROOT/workdir/$INSTANCE_ID/repo"
if [[ ! -d "$WORKREPO/.git" ]]; then
  mkdir -p "$ROOT/workdir/$INSTANCE_ID"
  git clone --quiet "https://github.com/$REPO.git" "$WORKREPO"
fi
cd "$WORKREPO"
git fetch --quiet origin
# Pro's setup block: reset, clean, checkout base, then checkout test file from solution commit.
bash -c "$BEFORE_CMD"
# Commit the post-setup state so we can diff "agent's changes" against it.
git -c user.email="setup@local" -c user.name="setup" add -A
git -c user.email="setup@local" -c user.name="setup" commit --allow-empty --quiet -m "pro setup"
SETUP_COMMIT=$(git rev-parse HEAD)
cd "$ROOT"

# --- 3. build user prompt (identical across conditions) ---
PROMPT_FILE="$ROOT/prompts/$INSTANCE_ID.txt"
mkdir -p "$ROOT/prompts"
export PROBLEM_STATEMENT REQUIREMENTS INTERFACE PROMPT_FILE
python - <<'PY'
import os
parts = [os.environ['PROBLEM_STATEMENT']]
req = os.environ.get('REQUIREMENTS','').strip()
ifc = os.environ.get('INTERFACE','').strip()
if req: parts += ['', '## Requirements', req]
if ifc: parts += ['', '## Interface', ifc]
parts += ['', 'You are at the repo root. The failing test(s) you must make pass are already present in the working tree. Fix by editing code files with the Edit tool. Do NOT modify test files. Save changes to disk and stop when done.']
open(os.environ['PROMPT_FILE'],'w').write('\n'.join(parts))
PY

# --- 4. run claude ---
UNIX=$(date +%s)
TMP_SESSION="$ROOT/sessions/_tmp_${CONDITION}_${UNIX}_$$.jsonl"
mkdir -p "$ROOT/sessions" "$ROOT/patches" "$ROOT/predictions" "$ROOT/logs/pro_eval"

CLAUDE_ARGS=(-p "$(cat "$PROMPT_FILE")"
  --model claude-haiku-4-5
  --permission-mode bypassPermissions
  --max-budget-usd 2
  --disallowedTools "WebFetch,WebSearch"
  --output-format stream-json --verbose)

if [[ "$CONDITION" == "caveman-ultra" ]]; then
  CLAUDE_ARGS+=(--append-system-prompt "$(cat "$SYS_PROMPT")")
fi

echo "[run_one] claude start"
(
  cd "$WORKREPO"
  claude "${CLAUDE_ARGS[@]}" > "$TMP_SESSION"
)

# --- 5. extract session id, rename ---
SID=$(python - <<PY
import json
events = [json.loads(l) for l in open('$TMP_SESSION')]
result = next(e for e in events if e.get('type')=='result')
print(result.get('session_id',''))
PY
)
SID8=${SID:0:8}
[[ -z "$SID8" ]] && { echo "[run_one] ERROR: no session_id"; exit 3; }

SESSION_FINAL="$ROOT/sessions/${INSTANCE_ID}__${CONDITION}__${SID8}.jsonl"
PATCH_FINAL="$ROOT/patches/${INSTANCE_ID}__${CONDITION}__${SID8}.patch"
PREDS_FINAL="$ROOT/predictions/${INSTANCE_ID}__${CONDITION}__${SID8}.json"
EVAL_OUT="$ROOT/logs/pro_eval/${INSTANCE_ID}__${CONDITION}__${SID8}"

mv "$TMP_SESSION" "$SESSION_FINAL"

# --- 6. capture patch (agent changes since post-setup state; commits stay included) ---
(
  cd "$WORKREPO"
  git -c user.email="agent@local" -c user.name="agent" add -A
  if ! git diff-index --quiet HEAD --; then
    git -c user.email="agent@local" -c user.name="agent" commit --quiet -m "agent changes" || true
  fi
  git diff "$SETUP_COMMIT" HEAD
) > "$PATCH_FINAL"
echo "[run_one] patch bytes: $(wc -c < "$PATCH_FINAL")"

# --- 7. Pro-format predictions (JSON array) ---
python - <<PY > "$PREDS_FINAL"
import json
patch = open('$PATCH_FINAL').read()
print(json.dumps([{'instance_id':'$INSTANCE_ID','patch':patch,'prefix':'$CONDITION'}], indent=2))
PY

# --- 8. grader: Pro harness with local Docker ---
mkdir -p "$EVAL_OUT"
echo "[run_one] grader start (local docker)"
(
  cd "$PRO_REPO"
  python swe_bench_pro_eval.py \
    --use_local_docker \
    --raw_sample_path "$PRO_CSV" \
    --patch_path "$PREDS_FINAL" \
    --output_dir "$EVAL_OUT" \
    --scripts_dir "$PRO_REPO/run_scripts" \
    --dockerhub_username jefzda \
    --num_workers 1 2>&1 | tail -30
) || echo "[run_one] WARNING: grader returned non-zero"

# --- 9. build Verified-style shim report.json, then log to CSV + print summary ---
SHIM_REPORT="$EVAL_OUT/shim_report.json"
python - <<PY
import json, os
import pandas as pd
iid = '$INSTANCE_ID'
cond = '$CONDITION'
out_file = f'$EVAL_OUT/{iid}/{cond}_output.json'
patch_applied = os.path.exists(out_file)
tests = json.load(open(out_file)).get('tests', []) if patch_applied else []
r = pd.read_csv('$PRO_CSV')
r = r[r['instance_id']==iid].iloc[0]
ftp = eval(r['fail_to_pass']); ptp = eval(r['pass_to_pass'])
by_name = {t['name']: t['status'] for t in tests}

def bucket(names):
    succ, fail = [], []
    for n in names:
        matches = [st for tn,st in by_name.items() if tn==n or tn.startswith(n+'/')]
        if matches and all(st=='PASSED' for st in matches):
            succ.append(n)
        else:
            fail.append(n)
    return succ, fail

ftp_s, ftp_f = bucket(ftp)
ptp_s, ptp_f = bucket(ptp)
resolved = patch_applied and not ftp_f and not ptp_f and (ftp or ptp or tests)

shim = {iid: {
    'patch_successfully_applied': patch_applied,
    'resolved': bool(resolved),
    'tests_status': {
        'FAIL_TO_PASS': {'success': ftp_s, 'failure': ftp_f},
        'PASS_TO_PASS': {'success': ptp_s, 'failure': ptp_f},
    },
}}
json.dump(shim, open('$SHIM_REPORT','w'))
PY

RUN_ID="grade_${INSTANCE_ID}__${CONDITION}__${SID8}"
SYS_ARG=()
if [[ "$CONDITION" == "caveman-ultra" ]]; then
  SYS_ARG=(--system-prompt-file "$SYS_PROMPT")
fi
python "$ROOT/scripts/log_experiment.py" \
  --session "$SESSION_FINAL" \
  --patch "$PATCH_FINAL" \
  --report "$SHIM_REPORT" \
  --instance-id "$INSTANCE_ID" \
  --model claude-haiku-4-5 \
  --condition "$CONDITION" \
  --prompt-file "$PROMPT_FILE" \
  "${SYS_ARG[@]}" \
  --grader-run-id "$RUN_ID" \
  --csv "$ROOT/data/experiments.csv" \
  --notes "pro pilot"

# summary line (read back the metrics we just wrote)
python - <<PY
import json
shim = json.load(open('$SHIM_REPORT'))['$INSTANCE_ID']
s = next(e for e in (json.loads(l) for l in open('$SESSION_FINAL')) if e.get('type')=='result')
ts = shim['tests_status']
ftp_s, ftp_f = len(ts['FAIL_TO_PASS']['success']), len(ts['FAIL_TO_PASS']['failure'])
ptp_s, ptp_f = len(ts['PASS_TO_PASS']['success']), len(ts['PASS_TO_PASS']['failure'])
print(f"[run_one] DONE: $INSTANCE_ID / $CONDITION / sid=$SID8 / resolved={shim['resolved']} / cost=\${s.get('total_cost_usd'):.4f} / turns={s.get('num_turns')} / out_tok={s.get('usage',{}).get('output_tokens')}")
print(f"         F2P: {ftp_s} succ / {ftp_f} fail   P2P: {ptp_s} succ / {ptp_f} fail")
PY

# Note: image pruning is now handled at the batch level by the orchestrator
# (to avoid re-pulls between the two conditions of the same instance).
