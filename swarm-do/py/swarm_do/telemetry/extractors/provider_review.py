"""Provider-review artifact extractor for findings.jsonl continuity.

Reads a `provider-findings.v2-draft` swarm-review artifact and emits rows
compatible with the general findings.v2 ledger. Provider-specific consensus
metadata remains in the per-run artifact; the ledger receives the shared
finding fields used by existing telemetry consumers.
"""

from __future__ import annotations

import datetime
import json
import sys
from typing import Any, Dict, List, Optional

from swarm_do.telemetry.ids import new_ulid


_LEDGER_FIELDS = (
    "finding_id",
    "run_id",
    "timestamp",
    "role",
    "issue_id",
    "severity",
    "category",
    "summary",
    "short_summary",
    "file_path",
    "line_start",
    "line_end",
    "schema_ok",
    "stable_finding_hash_v1",
    "duplicate_cluster_id",
)


def _iso_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger_row(finding: Dict[str, Any], run_id: str, issue_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(finding, dict):
        return None
    row = {field: finding.get(field) for field in _LEDGER_FIELDS}
    row["finding_id"] = row["finding_id"] if isinstance(row.get("finding_id"), str) else new_ulid()
    row["run_id"] = run_id
    row["timestamp"] = row["timestamp"] if isinstance(row.get("timestamp"), str) else _iso_utc_now()
    row["role"] = "agent-review"
    row["issue_id"] = issue_id
    row["severity"] = str(row.get("severity") or "info")
    row["category"] = str(row.get("category") or "provider-review")
    row["summary"] = str(row.get("summary") or "")
    if not row["summary"]:
        return None
    if row.get("short_summary") is not None:
        row["short_summary"] = str(row["short_summary"])
    row["schema_ok"] = bool(row.get("schema_ok"))
    return row


def extract(
    artifact_path: str,
    run_id: str,
    role: str,
    issue_id: str,
) -> List[Dict[str, Any]]:
    """Down-convert a swarm-review v2 artifact into findings.v2 ledger rows.

    The `role` argument is accepted for dispatcher parity; rows keep the
    existing `agent-review` role so they validate against findings.v2.
    """
    _ = role
    try:
        with open(artifact_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"extract-phase: cannot read provider-review artifact {artifact_path}: {exc}", file=sys.stderr)
        return []

    if not isinstance(payload, dict) or payload.get("schema_version") != "provider-findings.v2-draft":
        print(f"extract-phase: not a provider-findings.v2-draft artifact: {artifact_path}", file=sys.stderr)
        return []

    findings = payload.get("findings")
    if not isinstance(findings, list):
        print(f"extract-phase: no findings array in provider-review artifact {artifact_path}", file=sys.stderr)
        return []

    rows: List[Dict[str, Any]] = []
    for idx, finding in enumerate(findings):
        try:
            row = _ledger_row(finding, run_id, issue_id)
        except Exception as exc:  # noqa: BLE001 - fail-open extraction path
            print(f"extract-phase: skipping provider-review finding[{idx}]: {exc}", file=sys.stderr)
            continue
        if row is not None:
            rows.append(row)
    return rows
