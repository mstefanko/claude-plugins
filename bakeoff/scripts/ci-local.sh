#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/bakeoff-lib"
cd "$script_dir/.."

go_cache="${GOCACHE:-$(bakeoff_default_go_cache)}"
mkdir -p "$go_cache"
scripts/prompt-budget.sh
scripts/prompt-integrity.sh
shellcheck -s sh scripts/parallel-fanout-test.sh
scripts/parallel-fanout-test.sh
scripts/bakeoff-setup-tests
GOCACHE="$go_cache" go test ./...
GOCACHE="$go_cache" go test -race ./...
GOCACHE="$go_cache" python3 scripts/parity-go.py
