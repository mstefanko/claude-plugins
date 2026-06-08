#!/bin/sh
# Parallel multi-lens launcher: bakeoff-live-agent-eval.r001.multilens
# One subshell per lens child. No xargs -P, no eval, no set -e.
set -u

BAKEOFF_CLI="/Users/mstefanko/.claude/plugins/data/bakeoff-mstefanko-plugins/bin/bakeoff"
WORKDIR="/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff"
ARTDIR="$WORKDIR/.multilens-run"
mkdir -p "$ARTDIR"

cd "$WORKDIR" || exit 99

run_lens() {
  lens="$1"
  wo="bakeoff-live-agent-eval.r001.multilens.$lens.work-order.json"
  rid="bakeoff-live-agent-eval.r001.multilens.$lens"
  (
    "$BAKEOFF_CLI" research "$wo" \
      --run-id "$rid" \
      --base 386accc --diff --changed-files --no-triage \
      --json --quiet \
      >"$ARTDIR/$lens.stdout" 2>"$ARTDIR/$lens.stderr"
    echo "$?" >"$ARTDIR/$lens.exit"
  ) &
  echo "$!" >"$ARTDIR/$lens.pid"
  echo "launched $lens pid=$(cat "$ARTDIR/$lens.pid") run-id=$rid"
}

run_lens artifact-contract
run_lens test-coverage
run_lens operator-docs

wait
echo "all children settled"
for lens in artifact-contract test-coverage operator-docs; do
  echo "$lens exit=$(cat "$ARTDIR/$lens.exit" 2>/dev/null || echo MISSING)"
done
