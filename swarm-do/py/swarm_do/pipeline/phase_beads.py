"""Best-effort Beads notes for significant phase-session recovery transitions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

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
        )
    except Exception as exc:
        return {"written": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"written": False, "reason": (proc.stderr or proc.stdout).strip()}
    if kind in DEDUPE_KINDS:
        _remember_dedupe(base, run_id, fingerprint)
    return {"written": True, "bd_epic_id": bd_epic_id}


def _note_text(run_id: str, *, kind: str, phase_id: str | None, details: Mapping[str, Any]) -> str:
    lines = [f"swarm-do phase-session event: {kind}", f"run_id: {run_id}"]
    if phase_id:
        lines.append(f"phase_id: {phase_id}")
    for key in ("failure_kind", "next_retry_at", "recovery_context_path", "result_path", "handoff_path"):
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


__all__ = ["ALLOWLIST", "write_phase_beads_note"]
