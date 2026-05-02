"""Best-effort Beads notes for significant phase-session recovery transitions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .paths import resolve_data_dir
from .run_state import _atomic_json_write, utc_now


ALLOWLIST = {
    "phase_session_started",
    "phase_attempt_adopted",
    "phase_attempt_retry_scheduled",
    "phase_attempt_retry_exhausted",
    "phase_human_gated",
    "phase_hard_stop",
    "phase_session_complete",
}
DEDUPE_KINDS = {"phase_attempt_retry_scheduled"}
BdRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def create_run_epic(
    run_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    runner: BdRunner | None = None,
) -> dict[str, Any]:
    """Best-effort BEADS epic creation for a phase-session run."""

    issue_title = title or f"swarm-do run {run_id}"
    argv = [
        "bd",
        "create",
        issue_title,
        "--type",
        "epic",
        "--description",
        description or f"Controller-owned phase-session lifecycle for run {run_id}.",
        "--silent",
    ]
    return _run_bd_create(argv, runner=runner, key="bd_epic_id")


def create_stage_child(
    run_id: str,
    phase_id: str,
    stage_id: str,
    *,
    agent_role: str,
    parent_id: str | None,
    runner: BdRunner | None = None,
) -> dict[str, Any]:
    """Best-effort BEADS child creation for one planned stage."""

    if not parent_id:
        return {"created": False, "reason": "missing_parent_id", "bead_id": None}
    argv = [
        "bd",
        "create",
        f"{phase_id} {stage_id}",
        "--type",
        "task",
        "--assignee",
        agent_role,
        "--parent",
        parent_id,
        "--description",
        f"run_id: {run_id}\nphase_id: {phase_id}\nstage_id: {stage_id}\nagent_role: {agent_role}",
        "--silent",
    ]
    return _run_bd_create(argv, runner=runner, key="bead_id")


def close_stage_child(
    bead_id: str | None,
    *,
    commit_sha: str | None,
    runner: BdRunner | None = None,
) -> dict[str, Any]:
    if not bead_id:
        return {"closed": False, "reason": "missing_bead_id"}
    reason = f"adopted at {commit_sha}" if commit_sha else "stage completed without commit"
    try:
        proc = _run_bd(["bd", "close", bead_id, "--reason", reason], runner=runner, timeout=10)
    except subprocess.TimeoutExpired:
        return {"closed": False, "reason": "bd close timed out"}
    except Exception as exc:
        return {"closed": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"closed": False, "reason": (proc.stderr or proc.stdout).strip()}
    return {"closed": True, "bead_id": bead_id}


def mark_stage_blocked(
    bead_id: str | None,
    *,
    failure_kind: str,
    notes: str | None = None,
    runner: BdRunner | None = None,
) -> dict[str, Any]:
    if not bead_id:
        return {"updated": False, "reason": "missing_bead_id"}
    text = f"stage blocked: {failure_kind}"
    if notes:
        text += f"\n\n{notes}"
    try:
        proc = _run_bd(["bd", "update", bead_id, "--append-notes", text], runner=runner, timeout=10)
    except subprocess.TimeoutExpired:
        return {"updated": False, "reason": "bd update timed out"}
    except Exception as exc:
        return {"updated": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"updated": False, "reason": (proc.stderr or proc.stdout).strip()}
    return {"updated": True, "bead_id": bead_id}


def write_phase_beads_note(
    run_id: str,
    *,
    kind: str,
    bd_epic_id: str | None,
    phase_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    if kind not in ALLOWLIST:
        return {"written": False, "reason": "kind_not_allowlisted"}
    if not bd_epic_id:
        return {"written": False, "reason": "missing_bd_epic_id"}
    base = data_dir or resolve_data_dir()
    fingerprint = _fingerprint(kind, phase_id=phase_id, details=details or {})
    if kind in DEDUPE_KINDS and _deduped(base, run_id, fingerprint):
        return {"written": False, "reason": "deduped"}
    note = _note_text(run_id, kind=kind, phase_id=phase_id, details=details or {})
    try:
        proc = subprocess.run(
            ["bd", "update", bd_epic_id, "--notes", note],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"written": False, "reason": "bd update timed out"}
    except Exception as exc:
        return {"written": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"written": False, "reason": (proc.stderr or proc.stdout).strip()}
    if kind in DEDUPE_KINDS:
        _remember_dedupe(base, run_id, fingerprint)
    return {"written": True, "bd_epic_id": bd_epic_id}


def _run_bd_create(argv: list[str], *, runner: BdRunner | None, key: str) -> dict[str, Any]:
    try:
        proc = _run_bd(argv, runner=runner, timeout=10)
    except subprocess.TimeoutExpired:
        return {"created": False, "reason": "bd create timed out", key: None}
    except Exception as exc:
        return {"created": False, "reason": str(exc), key: None}
    if proc.returncode != 0:
        return {"created": False, "reason": (proc.stderr or proc.stdout).strip(), key: None}
    bead_id = _parse_created_id(proc.stdout)
    if not bead_id:
        return {"created": False, "reason": "bd create returned no issue id", key: None}
    return {"created": True, key: bead_id}


def _run_bd(
    argv: Sequence[str],
    *,
    runner: BdRunner | None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(argv)
    return subprocess.run(
        list(argv),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _parse_created_id(stdout: str) -> str | None:
    for token in stdout.replace("\n", " ").split():
        if token.strip():
            return token.strip()
    return None


def _note_text(run_id: str, *, kind: str, phase_id: str | None, details: Mapping[str, Any]) -> str:
    lines = [f"swarm-do phase-session event: {kind}", f"run_id: {run_id}"]
    if phase_id:
        lines.append(f"phase_id: {phase_id}")
    for key in (
        "failure_kind",
        "failure_category",
        "failure_retry_class",
        "failure_operator_title",
        "next_retry_at",
        "evidence_path",
        "recovery_context_path",
        "result_path",
        "handoff_path",
    ):
        value = details.get(key)
        if value:
            lines.append(f"{key}: {value}")
    lines.append(f"recorded_at: {utc_now()}")
    return "\n".join(lines)


def _fingerprint(kind: str, *, phase_id: str | None, details: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "kind": kind,
            "phase_id": phase_id,
            "failure_kind": details.get("failure_kind"),
            "next_retry_at": details.get("next_retry_at"),
        },
        sort_keys=True,
    )


def _dedupe_path(base: Path, run_id: str) -> Path:
    return base / "runs" / run_id / "phase_beads_dedupe.json"


def _deduped(base: Path, run_id: str, fingerprint: str) -> bool:
    path = _dedupe_path(base, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return fingerprint in set(payload.get("fingerprints") or [])


def _remember_dedupe(base: Path, run_id: str, fingerprint: str) -> None:
    path = _dedupe_path(base, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {"fingerprints": []}
    fingerprints = [item for item in payload.get("fingerprints") or [] if isinstance(item, str)]
    if fingerprint not in fingerprints:
        fingerprints.append(fingerprint)
    _atomic_json_write(path, {"fingerprints": fingerprints})


__all__ = [
    "ALLOWLIST",
    "close_stage_child",
    "create_run_epic",
    "create_stage_child",
    "mark_stage_blocked",
    "write_phase_beads_note",
]
