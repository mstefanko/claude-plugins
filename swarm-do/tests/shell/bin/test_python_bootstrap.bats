#!/usr/bin/env bats

load "../helpers/load"
load "../helpers/path_stub"

setup() {
  ROOT="$(repo_root)"
  BOOTSTRAP="$ROOT/bin/_lib/python-bootstrap.sh"
}

@test "python-bootstrap reports missing python3" {
  mkdir -p "$BATS_TEST_TMPDIR/empty"

  run env PATH="$BATS_TEST_TMPDIR/empty" /bin/bash -c "source '$BOOTSTRAP'"

  assert_failure
  assert_output_contains "python3 not found"
}

@test "python-bootstrap rejects python older than 3.10" {
  stub_command "python3" 'echo "Python 3.9.18"'

  run /bin/bash -c "source '$BOOTSTRAP'"

  assert_failure
  assert_output_contains "python3 >=3.10 required"
}

@test "python-bootstrap prepends repo py root to PYTHONPATH" {
  stub_command "python3" 'echo "Python 3.10.13"'

  run /bin/bash -c "source '$BOOTSTRAP'; printf '%s' \"\$PYTHONPATH\""

  assert_success
  [[ "$output" == "$ROOT/py:"* ]]
}
