#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${GOCACHE:-/tmp/bakeoff-go-cache}"
GOCACHE="${GOCACHE:-/tmp/bakeoff-go-cache}" go test ./...
GOCACHE="${GOCACHE:-/tmp/bakeoff-go-cache}" go test -race ./...
GOCACHE="${GOCACHE:-/tmp/bakeoff-go-cache}" python3 scripts/parity-go.py
