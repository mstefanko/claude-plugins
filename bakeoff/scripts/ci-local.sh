#!/usr/bin/env bash
set -euo pipefail

python3 -m pytest
python3 scripts/generate-prompt-fixtures.py --check
python3 scripts/parity-go.py --python-only
mkdir -p "${GOCACHE:-/tmp/bakeoff-go-cache}"
GOCACHE="${GOCACHE:-/tmp/bakeoff-go-cache}" go test ./...
