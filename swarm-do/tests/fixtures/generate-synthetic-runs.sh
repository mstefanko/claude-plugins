#!/usr/bin/env bash
# generate-synthetic-runs.sh — produce deterministic synthetic fixtures for swarm-telemetry tests.
#
# Generates:
#   synthetic-runs.jsonl     — ≥60 run rows covering all roles, complexities, phase_kinds, risk_tags
#   synthetic-findings.jsonl — ≥30 finding rows cross-referencing run_ids from runs fixture
#
# Output written to the directory containing this script.
# Safe to re-run: overwrites existing fixture files.

set -euo pipefail

_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_runs_out="${_dir}/synthetic-runs.jsonl"
_findings_out="${_dir}/synthetic-findings.jsonl"

command -v jq >/dev/null 2>&1 || { echo "generate-synthetic-runs.sh: jq required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "generate-synthetic-runs.sh: python3 required" >&2; exit 1; }

echo "generate-synthetic-runs.sh: generating synthetic fixtures..." >&2

# ---------------------------------------------------------------------------
# Generate synthetic-runs.jsonl via python3 for full control
# ---------------------------------------------------------------------------
python3 - "$_runs_out" "$_findings_out" <<'PYEOF'
import json, sys, math

RUNS_OUT    = sys.argv[1]
FINDINGS_OUT = sys.argv[2]

ROLES = [
    "agent-analysis",
    "agent-writer",
    "agent-review",
    "agent-codex-review",
    "agent-research",
    "agent-docs",
    "agent-code-synthesizer",
    "agent-spec-review",
    "agent-debug",
    "agent-clarify",
]

COMPLEXITIES  = ["low", "moderate", "high", None]
PHASE_KINDS   = ["feature", "bug", "refactor", "chore", "docs"]
BACKENDS      = ["claude", "codex"]
MODELS        = ["claude-sonnet-4-6", "gpt-4o", "claude-opus-4-7"]
EFFORTS       = ["low", "medium", "high", "xhigh"]
RISK_TAGS_POOL = [
    "security", "data-loss", "perf", "api-surface", "schema-change",
    "regression", "breaking-change", "migration", "external-dep", "auth"
]

SEVERITIES  = ["critical", "high", "medium", "low", "info"]
CATEGORIES  = ["correctness", "security", "performance", "style", "types", "boundary"]
ISSUES      = ["mstefanko-plugins-001", "mstefanko-plugins-002", "mstefanko-plugins-003",
               "mstefanko-plugins-004", "mstefanko-plugins-005"]

WRITER_STATUSES = ["DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT", None]
REVIEW_VERDICTS = ["APPROVED", "SPEC_MISMATCH", "NEEDS_CHANGES", None]
SETTING_SRCS    = ["plugin-config", "operator-override", "quota-bias", None]

# Base timestamp: 60 days ago from 2026-04-23T12:00:00Z
import datetime
BASE_TS = datetime.datetime(2026, 4, 23, 12, 0, 0, tzinfo=datetime.timezone.utc)
SIXTY_DAYS_AGO = BASE_TS - datetime.timedelta(days=60)

def make_ts(offset_seconds):
    t = SIXTY_DAYS_AGO + datetime.timedelta(seconds=offset_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")

def make_run_id(i):
    # Uppercase hex run id — matches ^[0-9A-Z_-]{1,64}$
    return "SYNTH{:06d}".format(i)

def make_finding_id(i):
    # 26-char Crockford base32 (simulated — use uppercase alphanum avoiding I/L/O/U)
    ALPHA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    val = i + 1000000
    chars = []
    for _ in range(26):
        chars.append(ALPHA[val % 32])
        val //= 32
    return ''.join(reversed(chars))

runs = []
run_ids = []  # collect for findings cross-ref

# Generate 66 runs (≥60 required)
TOTAL_RUNS = 66

for i in range(TOTAL_RUNS):
    role       = ROLES[i % len(ROLES)]
    complexity = COMPLEXITIES[i % len(COMPLEXITIES)]
    phase_kind = PHASE_KINDS[i % len(PHASE_KINDS)]
    backend    = BACKENDS[i % len(BACKENDS)]
    model      = MODELS[i % len(MODELS)]
    effort     = EFFORTS[i % len(EFFORTS)]
    issue_id   = ISSUES[i % len(ISSUES)]

    # risk_tags: null for ~20% (every 5th), else 2-3 tags
    if i % 5 == 0:
        risk_tags = None
    else:
        start = i % len(RISK_TAGS_POOL)
        tag_count = 2 + (i % 2)
        risk_tags = [RISK_TAGS_POOL[(start + k) % len(RISK_TAGS_POOL)] for k in range(tag_count)]

    # timestamps: spread across 60 days (offset in seconds)
    offset_start = int(i * (60 * 24 * 3600 / TOTAL_RUNS))
    wall_clock   = 45 + (i * 7) % 600  # 45..644 seconds
    offset_end   = offset_start + wall_clock

    ts_start = make_ts(offset_start)
    ts_end   = make_ts(offset_end)

    # exit_code: 0 for ~80%, 1 for ~20%
    exit_code = 1 if (i % 5 == 3) else 0

    # token/cost fields: realistic nulls for Phase 9a rows
    input_tokens         = 800 + i * 50 if i % 3 != 0 else None
    cached_input_tokens  = 200 + i * 10 if i % 4 != 0 else None
    output_tokens        = 300 + i * 20 if i % 3 != 0 else None
    estimated_cost_usd   = round(0.002 + i * 0.0005, 4) if i % 3 != 0 else None
    tool_call_count      = 5 + i % 20 if i % 2 == 0 else None
    cap_hit              = (i % 7 == 0) if i % 3 != 1 else None
    budget_breach        = (i % 11 == 0) if i % 3 != 2 else None

    writer_status  = WRITER_STATUSES[i % len(WRITER_STATUSES)] if role == "agent-writer" else None
    review_verdict = REVIEW_VERDICTS[i % len(REVIEW_VERDICTS)] if "review" in role else None
    setting_src    = SETTING_SRCS[i % len(SETTING_SRCS)]

    run_id = make_run_id(i)
    run_ids.append(run_id)

    row = {
        "run_id":               run_id,
        "timestamp_start":      ts_start,
        "timestamp_end":        ts_end,
        "backend":              backend,
        "model":                model,
        "effort":               effort,
        "prompt_bundle_hash":   "a" * 64 if i % 4 != 0 else None,
        "config_hash":          "b" * 64 if i % 5 != 0 else None,
        "role":                 role,
        "phase_kind":           phase_kind,
        "phase_complexity":     complexity,
        "risk_tags":            risk_tags,
        "issue_id":             issue_id,
        "repo":                 "mstefanko-plugins",
        "base_sha":             "a" * 40 if i % 6 != 0 else None,
        "head_sha":             "b" * 40 if i % 6 != 0 else None,
        "diff_size_bytes":      1024 + i * 100 if i % 6 != 0 else None,
        "input_tokens":         input_tokens,
        "cached_input_tokens":  cached_input_tokens,
        "output_tokens":        output_tokens,
        "estimated_cost_usd":   estimated_cost_usd,
        "wall_clock_seconds":   float(wall_clock),
        "tool_call_count":      tool_call_count,
        "cap_hit":              cap_hit,
        "budget_breach":        budget_breach,
        "schema_ok":            True,
        "exit_code":            exit_code,
        "setting_source":       setting_src,
        "writer_status":        writer_status,
        "review_verdict":       review_verdict,
        "last_429_at":          None,
    }
    runs.append(row)

with open(RUNS_OUT, "w") as f:
    for r in runs:
        f.write(json.dumps(r) + "\n")

print(f"generate-synthetic-runs.sh: wrote {len(runs)} rows to {RUNS_OUT}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Generate synthetic-findings.jsonl — ≥30 rows, cross-ref run_ids
# ---------------------------------------------------------------------------

FINDING_ROLES = ["agent-review", "agent-codex-review", "agent-spec-review"]

findings = []
TOTAL_FINDINGS = 35  # ≥30 required

for i in range(TOTAL_FINDINGS):
    role     = FINDING_ROLES[i % len(FINDING_ROLES)]
    # Cross-reference a run_id that used a review role (every 2nd run starting at 2)
    run_ref_idx = (i * 2 + 2) % len(run_ids)
    run_id   = run_ids[run_ref_idx]
    issue_id = ISSUES[i % len(ISSUES)]
    severity = SEVERITIES[i % len(SEVERITIES)]
    category = CATEGORIES[i % len(CATEGORIES)]

    offset_ts = int(i * (60 * 24 * 3600 / TOTAL_FINDINGS)) + 3600
    timestamp = make_ts(offset_ts)

    file_path  = f"swarm-do/bin/script-{i % 5}.sh" if i % 4 != 0 else None
    line_start = 10 + i * 3 if file_path else None
    line_end   = line_start + 5 if line_start else None

    summary = f"Synthetic finding #{i}: {category} issue of {severity} severity in {role}"

    row = {
        "finding_id": make_finding_id(i),
        "run_id":     run_id,
        "timestamp":  timestamp,
        "role":       role,
        "issue_id":   issue_id,
        "severity":   severity,
        "category":   category,
        "summary":    summary,
        "file_path":  file_path,
        "line_start": line_start,
        "line_end":   line_end,
        "schema_ok":  True,
    }
    findings.append(row)

with open(FINDINGS_OUT, "w") as f:
    for r in findings:
        f.write(json.dumps(r) + "\n")

print(f"generate-synthetic-runs.sh: wrote {len(findings)} rows to {FINDINGS_OUT}", file=sys.stderr)
PYEOF

echo "generate-synthetic-runs.sh: done." >&2
