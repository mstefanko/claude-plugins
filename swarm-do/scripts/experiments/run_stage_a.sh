#!/usr/bin/env bash
# Stage A driver — runs E6, E10, E11, E12, then E9 (the heaviest of the cheap probes).
# Skips experiments whose summary.md already exists, unless FORCE=1 in env.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-/tmp/swarmdaddy-experiments}"
mkdir -p "$EXPERIMENT_ROOT"

run_one() {
  local exp="$1"
  local script="$HERE/${exp}.sh"
  local summary="$EXPERIMENT_ROOT/${exp}/summary.md"
  if [ -f "$summary" ] && [ "${FORCE:-0}" != "1" ]; then
    echo "[skip] $exp (summary exists; FORCE=1 to rerun)"
    return 0
  fi
  echo "==== $exp ===="
  bash "$script"
  echo
}

run_one e6
run_one e10
run_one e11
run_one e12
run_one e9

echo
echo "==== Aggregate cost ===="
total=0
for exp in e6 e10 e11 e12 e9-n2 e9-n4 e9-n8 e9-n16; do
  c=$(python3 - "$EXPERIMENT_ROOT/$exp/stream.jsonl" 2>/dev/null <<'PY'
import json, sys, os
p = sys.argv[1]
if not os.path.exists(p): print(0); sys.exit(0)
with open(p) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if ev.get("type") == "result":
            print(ev.get("total_cost_usd", 0))
            sys.exit(0)
print(0)
PY
)
  printf '%-10s %s\n' "$exp" "$c"
  total=$(python3 -c "print($total + ($c if isinstance($c, (int,float)) else float('$c' or 0)))")
done
printf '%-10s %s\n' "TOTAL" "$total"
