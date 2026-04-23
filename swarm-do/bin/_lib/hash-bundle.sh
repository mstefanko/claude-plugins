#!/usr/bin/env bash
# hash-bundle.sh — compute SHA-256 of the prompt bundle for a swarm role.
#
# Usage: hash-bundle.sh <role> <backend>
#
# Output: 64-char lowercase hex SHA-256 of (shared.md + <backend>.md) on stdout.
# Exit 0 on success. Exit 1 to stderr if bundle files are missing.
#
# Portability: tries shasum -a 256 (macOS) then sha256sum (Linux).
#
# Sourced by swarm-run EXIT trap. May also be invoked standalone.

set -euo pipefail

# shellcheck source=paths.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/paths.sh"

_role="${1:-}"
_backend="${2:-}"

if [[ -z "$_role" || -z "$_backend" ]]; then
  echo "hash-bundle.sh: usage: hash-bundle.sh <role> <backend>" >&2
  exit 1
fi

_shared="${ROLES_DIR}/${_role}/shared.md"
_overlay="${ROLES_DIR}/${_role}/${_backend}.md"

if [[ ! -f "$_shared" ]]; then
  echo "hash-bundle.sh: missing bundle file: $_shared" >&2
  exit 1
fi
if [[ ! -f "$_overlay" ]]; then
  echo "hash-bundle.sh: missing bundle file: $_overlay" >&2
  exit 1
fi

# Compute hash — try shasum (macOS), fall back to sha256sum (Linux).
if command -v shasum >/dev/null 2>&1; then
  cat "$_shared" "$_overlay" | shasum -a 256 | awk '{print $1}'
elif command -v sha256sum >/dev/null 2>&1; then
  cat "$_shared" "$_overlay" | sha256sum | awk '{print $1}'
else
  echo "hash-bundle.sh: neither shasum nor sha256sum found on PATH" >&2
  exit 1
fi
