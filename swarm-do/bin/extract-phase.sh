#!/usr/bin/env bash
# extract-phase.sh — extract findings from a codex findings.json into findings.jsonl.
#
# Usage:
#   extract-phase.sh <findings-json> <run-id> <role> <issue-id>
#   extract-phase.sh --test
#
# Arguments:
#   findings-json   path to a codex findings.json (agent-codex-review output)
#   run-id          parent run_id from runs.jsonl (passed through verbatim)
#   role            swarm role that produced the findings (e.g. agent-codex-review)
#   issue-id        beads issue identifier
#
# Output: appends one JSONL row per finding to ${CLAUDE_PLUGIN_DATA}/telemetry/findings.jsonl
#
# Fail-open: any error prints a warning to stderr and exits 0. The pipeline
# exit code is never changed by this extractor.
#
# Scope: codex-only. Claude reviewer format is undefined (deferred to 9b-claude).
# Non-codex roles are skipped with a logged warning — not treated as an error.

set -euo pipefail

# ---------------------------------------------------------------------------
# Locate _lib relative to this script.
# ---------------------------------------------------------------------------
_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_lib_dir="${_script_dir}/_lib"

# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--test" ]]; then
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

  _check_pattern() {
    local _desc="$1" _got="$2" _pattern="$3"
    if [[ "$_got" =~ $_pattern ]]; then
      echo "  PASS: $_desc"
      (( _pass++ )) || true
    else
      echo "  FAIL: $_desc — got '$_got', does not match /$_pattern/"
      (( _fail++ )) || true
    fi
  }

  echo "=== extract-phase.sh --test ==="
  echo ""
  echo "--- normalize-path ---"

  # normalize-path: WORKTREE_ROOT strip
  _norm="${_lib_dir}/normalize-path.sh"
  if [[ -x "$_norm" ]]; then
    _t1_out="$(WORKTREE_ROOT="/tmp/test-wt/repo" bash "$_norm" "/tmp/test-wt/repo/internal/api/foo.go" 2>/dev/null || true)"
    _check "normalize-path strips WORKTREE_ROOT" "$_t1_out" "internal/api/foo.go"
  else
    echo "  FAIL: normalize-path.sh not found at $_norm"
    (( _fail++ )) || true
  fi

  echo ""
  echo "--- stable_finding_hash_v1 rounding ---"

  # Hash inputs: file_normalized | category_class | line_bucket | short_summary_tokens
  _compute_hash() {
    local _fnorm="$1" _cat="$2" _line="$3" _summary="$4"
    local _bucket=$(( _line / 10 ))
    local _input="${_fnorm}|${_cat}|${_bucket}|${_summary}"
    if command -v shasum >/dev/null 2>&1; then
      printf '%s' "$_input" | shasum -a 256 | awk '{print $1}'
    else
      printf '%s' "$_input" | sha256sum | awk '{print $1}'
    fi
  }

  _h47="$(_compute_hash "internal/api/foo.go" "boundary" 47 "window uses exclusive upper bound")"
  _h49="$(_compute_hash "internal/api/foo.go" "boundary" 49 "window uses exclusive upper bound")"
  _h52="$(_compute_hash "internal/api/foo.go" "boundary" 52 "window uses exclusive upper bound")"

  _check "line_start=47 and line_start=49 hash identically (both bucket=4)" "$_h47" "$_h49"

  if [[ "$_h47" != "$_h52" ]]; then
    echo "  PASS: line_start=47 and line_start=52 hash differently (bucket 4 vs 5)"
    (( _pass++ )) || true
  else
    echo "  FAIL: line_start=47 and line_start=52 produced same hash — bucket rounding broken"
    (( _fail++ )) || true
  fi

  _check_pattern "stable_finding_hash_v1 is 64-char lowercase hex" "$_h47" "^[0-9a-f]{64}$"

  echo ""
  echo "--- finding_id (26-char Crockford ULID) ---"

  if command -v python3 >/dev/null 2>&1; then
    _fid="$(python3 -c "
import time, os
t = int(time.time() * 1000)
r = int.from_bytes(os.urandom(10), 'big')
A = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
print(''.join(A[(t>>(9-i)*5)&31] for i in range(10)) + ''.join(A[(r>>(15-i)*5)&31] for i in range(16)))
" 2>/dev/null || true)"
    if [[ -n "$_fid" ]]; then
      _check_pattern "finding_id is 26-char Crockford base32" "$_fid" "^[0-9A-HJKMNP-TV-Z]{26}$"
      _fid_len="${#_fid}"
      _check "finding_id length is 26" "$_fid_len" "26"
    else
      echo "  FAIL: python3 ULID generation produced empty string"
      (( _fail++ )) || true
    fi
  else
    echo "  SKIP: python3 not available"
  fi

  echo ""
  echo "--- fail-open: unwritable findings.jsonl ---"

  _bad_dir="$(mktemp -d /tmp/extract-phase-test-XXXXXX)"
  chmod 000 "$_bad_dir"
  _fopen_rc=0
  ( CLAUDE_PLUGIN_DATA="$_bad_dir" bash "$0" /dev/null "TESTRUNID00000000000000000" "agent-codex-review" "test-issue" 2>/dev/null ) || _fopen_rc=$?
  chmod 755 "$_bad_dir" && rm -rf "$_bad_dir"
  _check "fail-open: exits 0 when findings.jsonl unwritable" "$_fopen_rc" "0"

  echo ""
  echo "=== extract-phase self-test: ${_pass} passed, ${_fail} failed ==="
  [[ "$_fail" -eq 0 ]] && exit 0 || exit 1
fi

# ---------------------------------------------------------------------------
# Main extraction — wrapped in subshell for fail-open behavior.
# Any failure exits the subshell but the outer script always exits 0.
# ---------------------------------------------------------------------------
(
  _findings_json="${1:-}"
  _run_id="${2:-}"
  _role="${3:-}"
  _issue_id="${4:-}"

  if [[ -z "$_findings_json" || -z "$_run_id" || -z "$_role" || -z "$_issue_id" ]]; then
    echo "extract-phase.sh: usage: extract-phase.sh <findings-json> <run-id> <role> <issue-id>" >&2
    exit 0
  fi

  # Scope: codex-only.
  if [[ "$_role" != "agent-codex-review" ]]; then
    echo "extract-phase.sh: role '$_role' is not agent-codex-review — skipping (Claude reviewer format undefined, deferred to 9b-claude)" >&2
    exit 0
  fi

  if [[ ! -f "$_findings_json" ]]; then
    echo "extract-phase.sh: findings.json not found: $_findings_json" >&2
    exit 0
  fi

  # Guard: CLAUDE_PLUGIN_DATA must be set.
  if [[ -z "${CLAUDE_PLUGIN_DATA:-}" ]]; then
    echo "extract-phase.sh: CLAUDE_PLUGIN_DATA unset — skipping findings write" >&2
    exit 0
  fi

  _tel_dir="${CLAUDE_PLUGIN_DATA}/telemetry"
  _norm="${_lib_dir}/normalize-path.sh"

  # Ensure telemetry directory exists.
  mkdir -p "$_tel_dir" 2>/dev/null || {
    echo "extract-phase.sh: cannot create telemetry dir $_tel_dir" >&2
    exit 0
  }

  _findings_out="${_tel_dir}/findings.jsonl"

  # Verify output file is writable (fail-open if not).
  if ! touch "$_findings_out" 2>/dev/null; then
    echo "extract-phase.sh: findings.jsonl not writable: $_findings_out" >&2
    exit 0
  fi

  # Parse findings array length.
  _count="$(jq '.findings | length' "$_findings_json" 2>/dev/null || echo "0")"
  if [[ "$_count" -eq 0 ]]; then
    echo "extract-phase.sh: no findings in $_findings_json" >&2
    exit 0
  fi

  _ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  _appended=0

  for (( _i=0; _i<_count; _i++ )); do
    # Extract per-finding fields via jq.
    _finding="$(jq -c ".findings[${_i}]" "$_findings_json" 2>/dev/null || true)"
    [[ -n "$_finding" ]] || continue

    _severity_raw="$(printf '%s' "$_finding" | jq -r '.severity // "info"')"
    _category_raw="$(printf '%s' "$_finding" | jq -r '.category // "info"')"
    _location="$(printf '%s' "$_finding" | jq -r '.location // ""')"
    _rationale="$(printf '%s' "$_finding" | jq -r '.rationale // ""')"

    # --- Map severity: codex uses warning/error/critical/info ---
    case "$_severity_raw" in
      warning)  _severity="high"     ;;
      error)    _severity="critical" ;;
      critical) _severity="critical" ;;
      info)     _severity="info"     ;;
      high)     _severity="high"     ;;
      medium)   _severity="medium"   ;;
      low)      _severity="low"      ;;
      *)        _severity="info"     ;;
    esac

    # --- Map category_class ---
    case "$_category_raw" in
      types|null) _category_class="types_or_null" ;;
      *)          _category_class="$_category_raw" ;;
    esac

    # --- Parse location "file:line_start-line_end" or "file:line" ---
    _file_raw=""
    _line_start=""
    _line_end=""
    if [[ -n "$_location" && "$_location" == *":"* ]]; then
      _file_raw="${_location%%:*}"
      _line_part="${_location#*:}"
      if [[ "$_line_part" == *"-"* ]]; then
        _line_start="${_line_part%-*}"
        _line_end="${_line_part#*-}"
      else
        _line_start="$_line_part"
        _line_end="$_line_part"
      fi
      # Validate numeric.
      [[ "$_line_start" =~ ^[0-9]+$ ]] || _line_start=""
      [[ "$_line_end"   =~ ^[0-9]+$ ]] || _line_end=""
    fi

    # --- Normalize file path ---
    _file_normalized=""
    if [[ -n "$_file_raw" ]]; then
      if [[ -x "$_norm" ]]; then
        _file_normalized="$(bash "$_norm" "$_file_raw" 2>/dev/null || echo "$_file_raw")"
      else
        _file_normalized="$_file_raw"
      fi
    fi

    # --- short_summary: strip leading verb from rationale, trim to 200 chars ---
    # Strip the first word if it looks like a verb (capitalized word followed by lowercase chars + space).
    _short_summary="$(printf '%s' "$_rationale" | sed 's/^[A-Z][a-z]*[a-z] //' | sed 's/^[[:space:]]*//' | cut -c1-200)"

    # --- stable_finding_hash_v1 ---
    # Algorithm: sha256( file_normalized | category_class | line_bucket | short_summary_tokens )
    # line_bucket = floor(line_start / 10)
    # This is stable_finding_hash_v1 — do NOT change algorithm without bumping to _v2.
    _hash_v1=""
    if [[ -n "$_file_normalized" && -n "$_line_start" ]]; then
      _line_bucket=$(( _line_start / 10 ))
      _hash_input="${_file_normalized}|${_category_class}|${_line_bucket}|${_short_summary}"
      if command -v shasum >/dev/null 2>&1; then
        _hash_v1="$(printf '%s' "$_hash_input" | shasum -a 256 | awk '{print $1}')"
      elif command -v sha256sum >/dev/null 2>&1; then
        _hash_v1="$(printf '%s' "$_hash_input" | sha256sum | awk '{print $1}')"
      fi
    fi

    # --- Generate finding_id: 26-char Crockford base32 ULID ---
    _finding_id=""
    if command -v python3 >/dev/null 2>&1; then
      _finding_id="$(python3 -c "
import time, os
t = int(time.time() * 1000)
r = int.from_bytes(os.urandom(10), 'big')
A = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
print(''.join(A[(t>>(9-i)*5)&31] for i in range(10)) + ''.join(A[(r>>(15-i)*5)&31] for i in range(16)))
" 2>/dev/null || true)"
    fi
    # awk Crockford fallback.
    if [[ -z "$_finding_id" ]]; then
      _finding_id="$(awk 'BEGIN{
        srand(); A="0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        s=""; for(i=0;i<26;i++) s=s substr(A, int(rand()*32)+1, 1)
        print s
      }')"
    fi

    # --- schema_ok: true if all required non-null fields are present ---
    _schema_ok="false"
    if [[ -n "$_finding_id" && -n "$_run_id" && -n "$_ts" && -n "$_role" \
          && -n "$_issue_id" && -n "$_severity" && -n "$_category_class" \
          && -n "$_rationale" && -n "$_short_summary" && -n "$_hash_v1" ]]; then
      _schema_ok="true"
    fi

    # --- file_path jq arg: quoted string or null ---
    _file_path_arg="null"
    if [[ -n "$_file_normalized" ]]; then
      _file_path_arg="$(printf '%s' "$_file_normalized" | jq -Rs .)"
    fi

    # --- Emit row via jq -n ---
    # duplicate_cluster_id is always null on append (stamped by indexer in Phase 9e).
    _row="$(jq -cn \
      --arg   finding_id              "$_finding_id" \
      --arg   run_id                  "$_run_id" \
      --arg   timestamp               "$_ts" \
      --arg   role                    "$_role" \
      --arg   issue_id                "$_issue_id" \
      --arg   severity                "$_severity" \
      --arg   category                "$_category_class" \
      --arg   summary                 "$_rationale" \
      --arg   short_summary           "$_short_summary" \
      --argjson file_path             "$_file_path_arg" \
      --argjson line_start            "$(if [[ -n "$_line_start" ]]; then echo "$_line_start"; else echo "null"; fi)" \
      --argjson line_end              "$(if [[ -n "$_line_end"   ]]; then echo "$_line_end";   else echo "null"; fi)" \
      --argjson schema_ok             "$_schema_ok" \
      --argjson stable_finding_hash_v1 "$(if [[ -n "$_hash_v1" ]]; then printf '"%s"' "$_hash_v1"; else echo "null"; fi)" \
      --argjson duplicate_cluster_id  "null" \
      '{
        finding_id:               $finding_id,
        run_id:                   $run_id,
        timestamp:                $timestamp,
        role:                     $role,
        issue_id:                 $issue_id,
        severity:                 $severity,
        category:                 $category,
        summary:                  $summary,
        short_summary:            $short_summary,
        file_path:                $file_path,
        line_start:               $line_start,
        line_end:                 $line_end,
        schema_ok:                $schema_ok,
        stable_finding_hash_v1:   $stable_finding_hash_v1,
        duplicate_cluster_id:     $duplicate_cluster_id
      }' 2>/dev/null || true)"

    if [[ -n "$_row" ]]; then
      printf '%s\n' "$_row" >> "$_findings_out" && (( _appended++ )) || true
    fi
  done

  echo "extract-phase.sh: appended ${_appended}/${_count} finding(s) from $_findings_json to $_findings_out" >&2

) 2>&1 || true

exit 0
