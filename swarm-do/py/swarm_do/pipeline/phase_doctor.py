"""Read-only recovery diagnostics for phase-session runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .domain import DoctorFinding, PhaseStatusReport, WORKTREE_STATUS_SENTINELS
from .paths import resolve_data_dir


Probe = Callable[[str, Path, Path | None], list[dict[str, Any]]]


def run_phase_doctor(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    probes: list[Probe] | None = None,
) -> dict[str, Any]:
    base = data_dir or resolve_data_dir()
    findings: list[dict[str, Any]] = []
    selected = probes or [
        _probe_phase_status,
        _probe_lease,
        _probe_worktree,
        _probe_prepared_dispatch,
    ]
    for probe in selected:
        try:
            findings.extend(probe(run_id, base, repo_root))
        except Exception as exc:
            findings.append(
                {
                    "id": "probe_error",
                    "severity": "error",
                    "probe": getattr(probe, "__name__", "unknown"),
                    "detail": str(exc),
                    "recommended_command": f"bin/swarm phases doctor {run_id} --json",
                }
            )
    ranked_records = sorted((DoctorFinding.from_mapping(item) for item in findings), key=lambda item: item.rank_key())
    ranked = [item.to_dict() for item in ranked_records]
    return {
        "run_id": run_id,
        "status": "ok" if not ranked else "findings",
        "finding_count": len(ranked),
        "findings": ranked,
        "recommended_command": ranked[0].get("recommended_command") if ranked else None,
    }


def format_phase_doctor(report: Mapping[str, Any]) -> str:
    lines = [f"phase doctor: {report.get('run_id')} status={report.get('status')} findings={report.get('finding_count')}"]
    for finding in report.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        record = DoctorFinding.from_mapping(finding)
        bits = [
            record.severity.upper(),
            record.id,
        ]
        if record.phase_id:
            bits.append(f"phase={record.phase_id}")
        lines.append("  - " + " ".join(bits))
        if record.detail:
            lines.append(f"      {record.detail}")
        if record.recommended_command:
            lines.append(f"      next: {record.recommended_command}")
    return "\n".join(lines)


def _probe_phase_status(run_id: str, data_dir: Path, repo_root: Path | None) -> list[dict[str, Any]]:
    from .phase_sessions import phase_status

    status = PhaseStatusReport.from_mapping(phase_status(run_id, data_dir=data_dir, repo_root=repo_root))
    current = status.status
    if current in {"ready", "complete"}:
        return []
    command = status.recommended_command or f"bin/swarm phases status {run_id}"
    return [
        {
            "id": "phase_status",
            "severity": "warning" if current != "drift" else "error",
            "detail": f"phase-session status is {current}",
            "recommended_command": command,
            "status": current,
        }
    ]


def _probe_lease(run_id: str, data_dir: Path, repo_root: Path | None) -> list[dict[str, Any]]:
    from .phase_sessions import parse_phase_datetime, phase_status

    status = PhaseStatusReport.from_mapping(phase_status(run_id, data_dir=data_dir, repo_root=repo_root))
    active = status.active_phase
    if active is None:
        return []
    expires = parse_phase_datetime(active.lease_expires_at)
    if expires is None or expires > datetime.now(UTC):
        return []
    phase_id = active.phase_id
    return [
        {
            "id": "lease_expired",
            "severity": "warning",
            "phase_id": phase_id,
            "detail": f"phase {phase_id} lease expired at {active.lease_expires_at}",
            "recommended_command": f"bin/swarm phases reap {run_id}",
        }
    ]


def _probe_worktree(run_id: str, data_dir: Path, repo_root: Path | None) -> list[dict[str, Any]]:
    from .execution_worktree import run_worktree_status

    status = run_worktree_status(run_id, data_dir=data_dir)
    if status.get("status") in WORKTREE_STATUS_SENTINELS:
        return []
    if status.get("base_drift_safe") and not any(
        status.get(key) for key in ("unadopted_commits", "dirty_paths", "identity_mismatch")
    ):
        return [
            {
                "id": "worktree_base_drift_safe",
                "severity": "info",
                "detail": ", ".join(status.get("drift") or []) or "worktree base drift can be rebuilt",
                "recommended_command": status.get("recommended_command") or f"bin/swarm worktrees status {run_id}",
                "worktree": status,
            }
        ]
    return [
        {
            "id": "worktree_drift",
            "severity": "warning",
            "detail": ", ".join(status.get("drift") or []) or "worktree drift detected",
            "recommended_command": status.get("recommended_command") or f"bin/swarm worktrees status {run_id}",
            "worktree": status,
        }
    ]


def _probe_prepared_dispatch(run_id: str, data_dir: Path, repo_root: Path | None) -> list[dict[str, Any]]:
    from .prepare import StalePreparedArtifactError, load_prepared_artifact, verify_prepared_payload

    payload = load_prepared_artifact(run_id, data_dir=data_dir, repo_root=repo_root)
    findings: list[dict[str, Any]] = []
    try:
        verify_prepared_payload(payload, repo_root=repo_root)
    except StalePreparedArtifactError as exc:
        reasons = list(exc.reasons)
        command = (
            f"bin/swarm prepare refresh-base {run_id}"
            if reasons == ["git_base_sha"]
            else f"bin/swarm prepare {payload.get('source_plan_path')}"
        )
        findings.append(
            {
                "id": "prepared_stale",
                "severity": "warning",
                "detail": "prepared artifact is stale: " + ", ".join(reasons),
                "recommended_command": command,
                "stale_reasons": reasons,
            }
        )
    except Exception as exc:
        findings.append(
            {
                "id": "prepared_dispatch_sidecars",
                "severity": "error",
                "detail": str(exc),
                "recommended_command": f"bin/swarm prepare refresh-base {run_id}",
            }
        )
    return findings

__all__ = ["format_phase_doctor", "run_phase_doctor"]
