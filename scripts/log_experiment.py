#!/usr/bin/env python3
"""Append a row to experiments.csv from a Claude Code session + SWE-bench harness report.

Usage:
  python log_experiment.py \
    --session session_baseline.jsonl \
    --patch prediction.patch \
    --report logs/run_evaluation/smoke_test/haiku45-baseline/psf__requests-1766/report.json \
    --instance-id psf__requests-1766 \
    --model claude-haiku-4-5 \
    --condition baseline \
    --prompt-file prompt.txt \
    --grader-run-id smoke_test \
    --csv experiments.csv
"""
import argparse, csv, fcntl, hashlib, json, os, subprocess
from datetime import datetime, timezone

FIELDS = [
    'experiment_id','timestamp','instance_id',
    'model','claude_cli_version','condition','prompt_file','system_prompt_hash',
    'claude_session_id','num_turns','duration_ms',
    'output_tokens','input_tokens_fresh','cache_creation_tokens','cache_read_tokens',
    'cost_usd','stop_reason','session_transcript_path',
    'patch_lines','patch_files_changed','patch_sha256',
    'grader_run_id','grader_timestamp',
    'patch_applied','resolved',
    'fail_to_pass_success','fail_to_pass_failure',
    'pass_to_pass_success','pass_to_pass_failure',
    'failed_tests','notes',
]


def parse_session(path):
    events = [json.loads(l) for l in open(path)]
    result = next((e for e in events if e.get('type') == 'result'), None)
    if not result:
        raise ValueError(f'No result event in {path}')
    return result


def parse_patch(path):
    content = open(path).read()
    lines = content.count('\n')
    # count "diff --git" occurrences robustly
    files = content.count('diff --git ')
    sha = hashlib.sha256(content.encode()).hexdigest()[:16]
    return lines, files, sha


def parse_report(path, instance_id):
    r = json.load(open(path))
    d = r[instance_id]
    ftp = d['tests_status']['FAIL_TO_PASS']
    ptp = d['tests_status']['PASS_TO_PASS']
    failed = ftp.get('failure', []) + ptp.get('failure', [])
    return {
        'patch_applied': d.get('patch_successfully_applied', False),
        'resolved': d.get('resolved', False),
        'ftp_success': len(ftp.get('success', [])),
        'ftp_failure': len(ftp.get('failure', [])),
        'ptp_success': len(ptp.get('success', [])),
        'ptp_failure': len(ptp.get('failure', [])),
        'failed_tests': ';'.join(failed),
    }


def file_hash(path):
    if not path or not os.path.exists(path):
        return ''
    return 'sha256:' + hashlib.sha256(open(path,'rb').read()).hexdigest()[:16]


def claude_cli_version():
    try:
        out = subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or out.stderr.strip()
    except Exception as e:
        return f'unknown ({e.__class__.__name__})'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--patch', required=True)
    ap.add_argument('--report', required=True)
    ap.add_argument('--instance-id', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--condition', required=True,
                    help='baseline / caveman-lite / caveman-full / caveman-ultra / ...')
    ap.add_argument('--prompt-file', default='')
    ap.add_argument('--system-prompt-file', default='',
                    help='e.g. caveman_ultra_system.md — hashed for reproducibility')
    ap.add_argument('--grader-run-id', required=True)
    ap.add_argument('--csv', required=True)
    ap.add_argument('--notes', default='')
    args = ap.parse_args()

    res = parse_session(args.session)
    usage = res.get('usage', {})
    patch_lines, patch_files, patch_sha = parse_patch(args.patch)
    rpt = parse_report(args.report, args.instance_id)

    now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    exp_id = f'exp_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}_{res.get("session_id","")[:8]}'

    row = {
        'experiment_id': exp_id,
        'timestamp': now,
        'instance_id': args.instance_id,
        'model': args.model,
        'claude_cli_version': claude_cli_version(),
        'condition': args.condition,
        'prompt_file': args.prompt_file,
        'system_prompt_hash': file_hash(args.system_prompt_file),
        'claude_session_id': res.get('session_id', ''),
        'num_turns': res.get('num_turns'),
        'duration_ms': res.get('duration_ms'),
        'output_tokens': usage.get('output_tokens'),
        'input_tokens_fresh': usage.get('input_tokens'),
        'cache_creation_tokens': usage.get('cache_creation_input_tokens'),
        'cache_read_tokens': usage.get('cache_read_input_tokens'),
        'cost_usd': res.get('total_cost_usd'),
        'stop_reason': res.get('stop_reason'),
        'session_transcript_path': args.session,
        'patch_lines': patch_lines,
        'patch_files_changed': patch_files,
        'patch_sha256': 'sha256:' + patch_sha,
        'grader_run_id': args.grader_run_id,
        'grader_timestamp': now,
        'patch_applied': rpt['patch_applied'],
        'resolved': rpt['resolved'],
        'fail_to_pass_success': rpt['ftp_success'],
        'fail_to_pass_failure': rpt['ftp_failure'],
        'pass_to_pass_success': rpt['ptp_success'],
        'pass_to_pass_failure': rpt['ptp_failure'],
        'failed_tests': rpt['failed_tests'],
        'notes': args.notes,
    }

    # Exclusive lock so parallel runs don't interleave rows. Lock is released on close.
    with open(args.csv, 'a', newline='') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        write_header = f.tell() == 0
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)
    print(f'Appended: {args.condition} / session {row["claude_session_id"][:8]} / grader={args.grader_run_id} / resolved={row["resolved"]}')


if __name__ == '__main__':
    main()
