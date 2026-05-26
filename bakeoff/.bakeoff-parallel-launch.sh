#!/bin/sh
# Parallel lens launcher for dogfood-manifest-telemetry-lenses.
# One subshell per child, separate stdout/stderr/exit/pid files,
# no xargs -P, no eval, no set -e.

BAKEOFF_CLI="/Users/mstefanko/.claude/plugins/data/bakeoff-mstefanko-plugins/bin/bakeoff"
WORKDIR="/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff"
LOGROOT="$WORKDIR/runs/.parallel/dogfood-manifest-telemetry-lenses"

cd "$WORKDIR" || { echo "cd-failed" >&2; exit 99; }
mkdir -p "$LOGROOT/correctness" "$LOGROOT/telemetry-schema" "$LOGROOT/docs-tests"

launch_lens() {
  lens="$1"
  wo="$2"
  rid="$3"
  ldir="$LOGROOT/$lens"
  (
    "$BAKEOFF_CLI" research "$wo" \
      --run-id "$rid" \
      --base HEAD \
      --diff \
      --json \
      --quiet \
      >"$ldir/stdout" 2>"$ldir/stderr"
    echo "$?" >"$ldir/exit"
  ) &
  echo "$!" >"$ldir/pid"
  echo "launched: $lens (pid=$(cat "$ldir/pid"), run-id=$rid)"
}

launch_lens correctness       "dogfood-manifest-telemetry-lenses.correctness.work-order.json"       "dogfood-manifest-telemetry-lenses.correctness"
launch_lens telemetry-schema  "dogfood-manifest-telemetry-lenses.telemetry-schema.work-order.json"  "dogfood-manifest-telemetry-lenses.telemetry-schema"
launch_lens docs-tests        "dogfood-manifest-telemetry-lenses.docs-tests.work-order.json"        "dogfood-manifest-telemetry-lenses.docs-tests"

echo "waiting for all 3 lens children to settle..."
wait
echo "all children settled."

for lens in correctness telemetry-schema docs-tests; do
  ldir="$LOGROOT/$lens"
  rc="$(cat "$ldir/exit" 2>/dev/null || echo missing)"
  stdb=$(wc -c <"$ldir/stdout" 2>/dev/null | tr -d ' ')
  errb=$(wc -c <"$ldir/stderr" 2>/dev/null | tr -d ' ')
  echo "$lens: exit=$rc stdout=${stdb}B stderr=${errb}B"
done
