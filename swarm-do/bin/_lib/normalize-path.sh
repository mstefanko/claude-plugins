#!/usr/bin/env bash
# normalize-path.sh — canonicalize a file path for stable_finding_hash_v1 input.
#
# Usage: normalize-path.sh <raw-path>
#
# Environment:
#   WORKTREE_ROOT  absolute path to the worktree root (may be empty/unset)
#
# Output: canonical repo-relative path, no leading slash. e.g. internal/api/foo.go
#   If neither WORKTREE_ROOT nor REPO_ROOT matches, emits the resolved path verbatim.
#
# Exit: always 0 (fail-open; errors to stderr).
#
# --test flag: self-test with synthetic paths; exits non-zero on failure.

set -euo pipefail

_raw="${1:-}"

# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------
if [[ "$_raw" == "--test" ]]; then
  _pass=0
  _fail=0
  _check() {
    local _desc="$1" _got="$2" _want="$3"
    if [[ "$_got" == "$_want" ]]; then
      echo "  PASS: $_desc"
      (( _pass++ )) || true
    else
      echo "  FAIL: $_desc — got '$_got', want '$_want'"
      (( _fail++ )) || true
    fi
  }

  # Test 1: WORKTREE_ROOT strip
  _t1_root="/tmp/test-wt/repo"
  _t1_in="/tmp/test-wt/repo/internal/api/foo.go"
  _t1_out="$(WORKTREE_ROOT="$_t1_root" bash "$0" "$_t1_in")"
  _check "WORKTREE_ROOT strip" "$_t1_out" "internal/api/foo.go"

  # Test 2: WORKTREE_ROOT empty — should passthrough
  _t2_in="internal/api/foo.go"
  _t2_out="$(WORKTREE_ROOT="" bash "$0" "$_t2_in")"
  _check "empty WORKTREE_ROOT passthrough" "$_t2_out" "internal/api/foo.go"

  # Test 3: path already relative — passthrough unchanged
  _t3_in="pkg/util/helper.go"
  _t3_out="$(WORKTREE_ROOT="" bash "$0" "$_t3_in")"
  _check "relative path passthrough" "$_t3_out" "pkg/util/helper.go"

  echo ""
  echo "normalize-path self-test: ${_pass} passed, ${_fail} failed"
  [[ "$_fail" -eq 0 ]] && exit 0 || exit 1
fi

if [[ -z "$_raw" ]]; then
  echo "normalize-path.sh: usage: normalize-path.sh <raw-path>" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: resolve symlinks
# realpath -m resolves without requiring the path to exist.
# macOS ships realpath via coreutils (brew) or falls back to readlink -f.
# ---------------------------------------------------------------------------
_resolved=""
if command -v realpath >/dev/null 2>&1; then
  _resolved="$(realpath -m "$_raw" 2>/dev/null || true)"
fi
if [[ -z "$_resolved" ]]; then
  # Fallback: readlink -f requires the path to exist; use raw if it doesn't.
  _resolved="$(readlink -f "$_raw" 2>/dev/null || echo "$_raw")"
fi

# ---------------------------------------------------------------------------
# Step 2: strip WORKTREE_ROOT prefix
# ---------------------------------------------------------------------------
if [[ -n "${WORKTREE_ROOT:-}" ]]; then
  _wt="${WORKTREE_ROOT%/}"
  if [[ "$_resolved" == "${_wt}/"* ]]; then
    _rel="${_resolved#"${_wt}/"}"
    printf '%s\n' "${_rel#/}"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: strip REPO_ROOT prefix (git rev-parse)
# ---------------------------------------------------------------------------
_repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "$_repo_root" ]]; then
  _rr="${_repo_root%/}"
  if [[ "$_resolved" == "${_rr}/"* ]]; then
    _rel="${_resolved#"${_rr}/"}"
    printf '%s\n' "${_rel#/}"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Step 4: strip any leading slash; emit verbatim if no prefix matched.
# ---------------------------------------------------------------------------
printf '%s\n' "${_resolved#/}"
