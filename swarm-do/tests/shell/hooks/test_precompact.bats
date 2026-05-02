#!/usr/bin/env bats

load "../helpers/load"

setup() {
  ROOT="$(repo_root)"
}

@test "precompact exits cleanly when CLAUDE_PLUGIN_DATA is unset" {
  run env -u CLAUDE_PLUGIN_DATA "$ROOT/hooks/precompact.sh"

  assert_success
}

@test "precompact exits cleanly when no active run exists" {
  mkdir -p "$BATS_TEST_TMPDIR/data"

  run env CLAUDE_PLUGIN_DATA="$BATS_TEST_TMPDIR/data" "$ROOT/hooks/precompact.sh"

  assert_success
}
