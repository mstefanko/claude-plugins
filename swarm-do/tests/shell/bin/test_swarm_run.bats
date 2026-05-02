#!/usr/bin/env bats

load "../helpers/load"

setup() {
  ROOT="$(repo_root)"
}

make_isolated_swarm_run() {
  local sandbox="$BATS_TEST_TMPDIR/swarm"
  mkdir -p "$sandbox/bin" "$sandbox/roles/agent-writer"
  cp "$ROOT/bin/swarm-run" "$sandbox/bin/swarm-run"
  cp -R "$ROOT/bin/_lib" "$sandbox/bin/_lib"
  cat > "$sandbox/bin/swarm" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-}" == "beads" && "${2:-}" == "check" ]]; then
  printf '{"rig":"test"}\n'
  exit 0
fi
exit 2
SH
  chmod +x "$sandbox/bin/swarm" "$sandbox/bin/swarm-run"
  printf 'shared\n' > "$sandbox/roles/agent-writer/shared.md"
  printf 'codex\n' > "$sandbox/roles/agent-writer/codex.md"
  printf 'claude\n' > "$sandbox/roles/agent-writer/claude.md"
  printf '%s\n' "$sandbox"
}

@test "swarm-run requires --backend" {
  run "$ROOT/bin/swarm-run" --issue bd-1 --role agent-writer

  assert_failure
  assert_output_contains "--backend is required"
}

@test "swarm-run rejects invalid --mode" {
  run "$ROOT/bin/swarm-run" --backend codex --issue bd-1 --role agent-writer --mode sideways

  assert_failure
  assert_output_contains "--mode must be normal|fallback|competition"
}

@test "swarm-run --dry-run does not invoke backend" {
  sandbox="$(make_isolated_swarm_run)"
  mkdir -p "$BATS_TEST_TMPDIR/bin"
  printf '#!/usr/bin/env bash\necho invoked > %q\nexit 99\n' "$BATS_TEST_TMPDIR/codex-called" > "$BATS_TEST_TMPDIR/bin/codex"
  cat > "$BATS_TEST_TMPDIR/bin/bd" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-}" == "show" ]]; then
  printf '{"assignee":"agent-writer"}\n'
  exit 0
fi
exit 0
SH
  chmod +x "$BATS_TEST_TMPDIR/bin/codex"
  chmod +x "$BATS_TEST_TMPDIR/bin/bd"

  run env PATH="$BATS_TEST_TMPDIR/bin:$PATH" "$sandbox/bin/swarm-run" \
    --backend codex --issue bd-1 --role agent-writer --dry-run

  assert_success
  assert_output_contains "dry-run: would invoke codex"
  [[ ! -f "$BATS_TEST_TMPDIR/codex-called" ]]
}
