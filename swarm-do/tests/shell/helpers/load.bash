repo_root() {
  cd "$BATS_TEST_DIRNAME/../../.." && pwd
}

assert_success() {
  if [[ "$status" -ne 0 ]]; then
    printf 'expected success, got status %s\n%s\n' "$status" "$output" >&2
    return 1
  fi
}

assert_failure() {
  if [[ "$status" -eq 0 ]]; then
    printf 'expected failure, got success\n%s\n' "$output" >&2
    return 1
  fi
}

assert_output_contains() {
  local needle="$1"
  if [[ "$output" != *"$needle"* ]]; then
    printf 'expected output to contain %q\n%s\n' "$needle" "$output" >&2
    return 1
  fi
}
