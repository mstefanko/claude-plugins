#!/bin/sh
set -u

cd "$(dirname "$0")/.."

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/bakeoff-fanout-test.XXXXXX") || exit 1
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

labels="security ux performance"
progress_log="$tmpdir/progress.log"

mock_child() {
  label=$1
  delay=$2
  code=$3
  output_mode=$4

  sleep "$delay"
  if [ "$output_mode" = "json" ]; then
    printf '{"label":"%s","result":"done"}\n' "$label"
  else
    printf 'not json for %s\n' "$label"
    printf 'artifact summary for %s\n' "$label" > "$tmpdir/$label.artifact"
  fi
  printf '%s stderr\n' "$label" >&2
  return "$code"
}

start_child() {
  label=$1
  delay=$2
  code=$3
  output_mode=$4
  (
    mock_child "$label" "$delay" "$code" "$output_mode"
    child_exit=$?
    printf '%s\n' "$child_exit" > "$tmpdir/$label.exit"
  ) > "$tmpdir/$label.stdout" 2> "$tmpdir/$label.stderr" &
  printf '%s\n' "$!" > "$tmpdir/$label.pid"
}

is_running() {
  label=$1
  [ -f "$tmpdir/$label.pid" ] || return 1
  pid=$(cat "$tmpdir/$label.pid")
  kill -0 "$pid" 2>/dev/null
}

classify_child() {
  label=$1
  if [ -f "$tmpdir/$label.exit" ]; then
    printf 'exit:%s\n' "$(cat "$tmpdir/$label.exit")"
    return 0
  fi
  if is_running "$label"; then
    printf 'running\n'
    return 0
  fi
  printf 'orphaned_child\n'
}

summary_source() {
  label=$1
  if grep -Fq '"label":"' "$tmpdir/$label.stdout" 2>/dev/null; then
    printf 'stdout-json\n'
    return 0
  fi
  if [ -f "$tmpdir/$label.artifact" ]; then
    printf 'artifact-fallback\n'
    return 0
  fi
  printf 'missing\n'
}

assert_contains() {
  path=$1
  needle=$2
  grep -Fq "$needle" "$path" || fail "$path missing $needle"
}

start_child security 1 0 json
start_child ux 1 1 json
start_child performance 2 4 artifact

printf 'parallel multi-lens: launched 3 lens runs\n' > "$progress_log"

while :; do
  done_count=0
  running=""
  for label in $labels; do
    state=$(classify_child "$label")
    case "$state" in
      exit:*)
        done_count=$((done_count + 1))
        if [ ! -f "$tmpdir/$label.seen" ]; then
          exit_code=${state#exit:}
          running_count=$((3 - done_count))
          printf 'parallel multi-lens: completed %s exit=%s; running %s/3\n' \
            "$label" "$exit_code" "$running_count" >> "$progress_log"
          : > "$tmpdir/$label.seen"
        fi
        ;;
      running)
        if [ -z "$running" ]; then
          running=$label
        else
          running="$running, $label"
        fi
        ;;
      *)
        fail "unexpected state for $label: $state"
        ;;
    esac
  done

  if [ "$done_count" -eq 3 ]; then
    break
  fi
  if [ -n "$running" ]; then
    printf 'parallel multi-lens: running %s/3: %s\n' "$((3 - done_count))" "$running" >> "$progress_log"
  fi
  sleep 1
done

for label in $labels; do
  wait "$(cat "$tmpdir/$label.pid")" 2>/dev/null || :
done

[ "$(cat "$tmpdir/security.exit")" = "0" ] || fail "security exit not captured"
[ "$(cat "$tmpdir/ux.exit")" = "1" ] || fail "ux exit not captured"
[ "$(cat "$tmpdir/performance.exit")" = "4" ] || fail "performance exit not captured"

assert_contains "$tmpdir/security.stdout" '"label":"security"'
assert_contains "$tmpdir/security.stderr" 'security stderr'
assert_contains "$tmpdir/ux.stdout" '"label":"ux"'
assert_contains "$tmpdir/ux.stderr" 'ux stderr'
assert_contains "$tmpdir/performance.stdout" 'not json for performance'
assert_contains "$tmpdir/performance.stderr" 'performance stderr'

[ "$(summary_source security)" = "stdout-json" ] || fail "security JSON summary not detected"
[ "$(summary_source performance)" = "artifact-fallback" ] || fail "artifact fallback not detected"

assert_contains "$progress_log" 'parallel multi-lens: launched 3 lens runs'
assert_contains "$progress_log" 'parallel multi-lens: running'
assert_contains "$progress_log" 'completed security exit=0'
assert_contains "$progress_log" 'completed ux exit=1'
assert_contains "$progress_log" 'completed performance exit=4'

(
  :
) &
stale_pid=$!
wait "$stale_pid" 2>/dev/null || :
printf '%s\n' "$stale_pid" > "$tmpdir/orphan.pid"
[ "$(classify_child orphan)" = "orphaned_child" ] || fail "orphaned child not classified"

printf 'Parallel fanout test OK\n'
