stub_command() {
  local name="$1" body="$2"
  local stub_dir="${BATS_TEST_TMPDIR}/stubs"
  mkdir -p "$stub_dir"
  printf '#!/usr/bin/env bash\n%s\n' "$body" > "$stub_dir/$name"
  chmod +x "$stub_dir/$name"
  export PATH="$stub_dir:$PATH"
}
