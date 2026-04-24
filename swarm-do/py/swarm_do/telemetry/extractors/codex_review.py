"""Codex-reviewer findings extractor — port of extract-phase.sh.legacy.

Reads a codex `findings.json` (list under top-level "findings") and emits
one row per finding matching the findings.v2 schema. All parity-critical
semantics (severity map, category_class rewrite, location parse, short
summary leading-verb strip) come straight from the bash implementation.

Plan ref: plans/phase-4-extractors.md workstream WS-2.

Fail-open: every extraction attempt is wrapped in try/except; malformed
findings are skipped with a stderr warning. The caller always receives a
list, possibly empty.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from swarm_do.telemetry.ids import new_ulid

from .hashing import stable_finding_hash_v1
from .paths import normalize_path


# ---------------------------------------------------------------------------
# Severity + category rewrite tables — verbatim from extract-phase.sh.legacy
# lines 212-227.
# ---------------------------------------------------------------------------

_SEVERITY_MAP: Dict[str, str] = {
    "warning": "high",
    "error": "critical",
    "critical": "critical",
    "info": "info",
    "high": "high",
    "medium": "medium",
    "low": "low",
}

_CATEGORY_REWRITES: Dict[str, str] = {
    "types": "types_or_null",
    "null": "types_or_null",
}

# sed 's/^[A-Z][a-z]*[a-z] //' in the legacy script strips a capitalized
# leading word (first letter uppercase, then 1+ lowercase letters, followed by
# a space). The final `[a-z]` in the bash class is redundant but we preserve
# the minimum-length-of-2 semantics by requiring 2+ lowercase chars.
_LEADING_VERB_RE = re.compile(r"^[A-Z][a-z]*[a-z] ")


def _map_severity(raw: str) -> str:
    return _SEVERITY_MAP.get(raw, "info")


def _category_class(raw: str) -> str:
    return _CATEGORY_REWRITES.get(raw, raw)


def _parse_location(location: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Parse `"file:line"` or `"file:line_start-line_end"`.

    Returns (file_raw, line_start, line_end). Any portion that fails integer
    validation becomes None, matching the bash guard
    `[[ "$_line_start" =~ ^[0-9]+$ ]] || _line_start=""`.
    """
    if not location or ":" not in location:
        return (None, None, None)

    # Legacy uses ${location%%:*} / ${location#*:} — split once from the LEFT.
    # But file paths can contain ':' on Windows; the bash does the same so we
    # port it verbatim for parity.
    file_raw, _, line_part = location.partition(":")
    if "-" in line_part:
        start_str, _, end_str = line_part.partition("-")
    else:
        start_str = end_str = line_part

    line_start = int(start_str) if start_str.isdigit() else None
    line_end = int(end_str) if end_str.isdigit() else None
    return (file_raw or None, line_start, line_end)


def _short_summary(rationale: str) -> str:
    """Strip leading capitalized verb, trim whitespace, cap at 200 chars.

    Matches `sed 's/^[A-Z][a-z]*[a-z] //' | sed 's/^[[:space:]]*//' | cut -c1-200`.
    """
    stripped = _LEADING_VERB_RE.sub("", rationale, count=1)
    stripped = stripped.lstrip()
    return stripped[:200]


def _build_row(
    finding: Dict[str, Any],
    run_id: str,
    role: str,
    issue_id: str,
    timestamp: str,
) -> Optional[Dict[str, Any]]:
    """Return a findings.v2 row dict, or None if the finding is empty."""
    if not isinstance(finding, dict):
        return None

    severity_raw = str(finding.get("severity") or "info")
    category_raw = str(finding.get("category") or "info")
    location = str(finding.get("location") or "")
    rationale = str(finding.get("rationale") or "")

    severity = _map_severity(severity_raw)
    category = _category_class(category_raw)
    file_raw, line_start, line_end = _parse_location(location)
    short_summary = _short_summary(rationale)

    file_path: Optional[str] = None
    if file_raw:
        try:
            file_path = normalize_path(file_raw)
        except Exception as exc:  # noqa: BLE001 — fail-open per plan
            print(
                f"extract-phase: normalize_path failed for {file_raw!r}: {exc}",
                file=sys.stderr,
            )
            file_path = file_raw

    hash_v1: Optional[str] = None
    if file_path and line_start is not None:
        hash_v1 = stable_finding_hash_v1(file_path, category, line_start, short_summary)

    # schema_ok: True when every required non-null field plus the hash exist.
    schema_ok = all(
        [
            run_id,
            timestamp,
            role,
            issue_id,
            severity,
            category,
            rationale,
            short_summary,
            hash_v1,
        ]
    )

    return {
        "finding_id": new_ulid(),
        "run_id": run_id,
        "timestamp": timestamp,
        "role": role,
        "issue_id": issue_id,
        "severity": severity,
        "category": category,
        "summary": rationale,
        "short_summary": short_summary,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "schema_ok": bool(schema_ok),
        "stable_finding_hash_v1": hash_v1,
        "duplicate_cluster_id": None,
    }


def _iso_utc_now() -> str:
    # Match bash `date -u +"%Y-%m-%dT%H:%M:%SZ"` (no fractional seconds).
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract(
    findings_json_path: str,
    run_id: str,
    role: str,
    issue_id: str,
) -> List[Dict[str, Any]]:
    """Parse a codex `findings.json` into findings.v2 rows.

    Fail-open: returns [] on any I/O or JSON error after logging to stderr.
    """
    try:
        with open(findings_json_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"extract-phase: cannot read {findings_json_path}: {exc}",
            file=sys.stderr,
        )
        return []

    findings_list = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(findings_list, list):
        print(
            f"extract-phase: no findings array in {findings_json_path}",
            file=sys.stderr,
        )
        return []

    timestamp = _iso_utc_now()
    rows: List[Dict[str, Any]] = []
    for idx, finding in enumerate(findings_list):
        try:
            row = _build_row(finding, run_id, role, issue_id, timestamp)
        except Exception as exc:  # noqa: BLE001 — fail-open per plan
            print(
                f"extract-phase: skipping malformed finding[{idx}]: {exc}",
                file=sys.stderr,
            )
            continue
        if row is not None:
            rows.append(row)
    return rows
