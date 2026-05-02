#!/usr/bin/env bats

load "../helpers/load"

setup() {
  ROOT="$(repo_root)"
}

@test "extract-phase forwards --test to the Python extractor self-test" {
  run "$ROOT/bin/extract-phase.sh" --test

  assert_success
}

@test "extract-phase missing args remains fail-open with usage warning" {
  run "$ROOT/bin/extract-phase.sh"

  assert_success
  assert_output_contains "extract-phase: usage"
}
