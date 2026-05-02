#!/usr/bin/env bats

load "../helpers/load"

setup() {
  ROOT="$(repo_root)"
  NORMALIZE="$ROOT/bin/_lib/normalize-path.sh"
}

@test "normalize-path strips WORKTREE_ROOT after trailing slash canonicalization" {
  mkdir -p "$BATS_TEST_TMPDIR/repo/src/pkg"

  run env WORKTREE_ROOT="$BATS_TEST_TMPDIR/repo" "$NORMALIZE" "$BATS_TEST_TMPDIR/repo/src/pkg/"

  assert_success
  [[ "$output" == "src/pkg" ]]
}

@test "normalize-path collapses dot segments before stripping WORKTREE_ROOT" {
  mkdir -p "$BATS_TEST_TMPDIR/repo/src/pkg"

  run env WORKTREE_ROOT="$BATS_TEST_TMPDIR/repo" "$NORMALIZE" "$BATS_TEST_TMPDIR/repo/src/./pkg/../pkg"

  assert_success
  [[ "$output" == "src/pkg" ]]
}

@test "normalize-path treats /var and /private/var forms equivalently on macOS" {
  if [[ ! -e /var/folders || ! -e /private/var/folders ]]; then
    skip "macOS /var canonicalization path not present"
  fi

  run "$NORMALIZE" /var/folders
  assert_success
  from_var="$output"

  run "$NORMALIZE" /private/var/folders
  assert_success
  [[ "$output" == "$from_var" ]]
}
