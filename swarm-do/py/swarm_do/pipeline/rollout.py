"""Rollout status state for cross-backend swarm-do adoption."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_data_dir


PHASE_0_DECISIONS = {"GO-EVERY-DO", "GO-TARGETED", "NO-GO", "DOGFOOD", "pending"}
PHASE_0_MODES = {"A", "B", "plugin", "none"}
STATUSES = {"pending", "live", "rolled-back", "complete", "abandoned", "shadow"}
PATTERN_5_DECISIONS = {"AUTO-DISPATCH", "MANUAL-ONLY", "NO-GO", "pending"}
B1_STATUSES = {"pending", "shadow", "live", "rolled-back"}
BACKENDS = {"claude", "codex"}
TOP_KEYS = {"schema_version", "phase_0", "phase_1", "pattern_5_trial", "b1_dispatcher", "role_promotions"}
PHASE_0_KEYS = {"decision", "selected_mode", "decided_on", "cohort_run_date", "notes"}
PHASE_1_KEYS = {"status", "activated_on", "rolled_back_on", "rollback_reason"}
PATTERN_5_KEYS = {"status", "completed_on", "decision", "phases_sampled", "notes"}
B1_KEYS = {"status", "shadow_started_on", "live_cutover_on", "rolled_back_on", "notes"}
ROLE_KEYS = {"primary", "promoted_on", "measurement_ref"}


def default_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase_0": {
            "decision": "pending",
            "selected_mode": "none",
            "decided_on": None,
            "cohort_run_date": None,
            "notes": "",
        },
        "phase_1": {
            "status": "pending",
            "activated_on": None,
            "rolled_back_on": None,
            "rollback_reason": None,
        },
        "pattern_5_trial": {
            "status": "pending",
            "completed_on": None,
            "decision": "pending",
            "phases_sampled": 0,
            "notes": "",
        },
        "b1_dispatcher": {
            "status": "pending",
            "shadow_started_on": None,
            "live_cutover_on": None,
            "rolled_back_on": None,
            "notes": "",
        },
        "role_promotions": {
            "agent-docs": {"primary": "claude", "promoted_on": None, "measurement_ref": None},
            "agent-spec-review": {"primary": "claude", "promoted_on": None, "measurement_ref": None},
            "agent-clarify": {"primary": "claude", "promoted_on": None, "measurement_ref": None},
            "agent-writer.simple": {"primary": "claude", "promoted_on": None, "measurement_ref": None},
        },
    }


def state_path() -> Path:
    return resolve_data_dir() / "state" / "rollout-status.json"


def audit_path() -> Path:
    return resolve_data_dir() / "state" / "rollout-status.log"


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return default_state()
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    merged = default_state()
    _deep_update(merged, state)
    validate_state(merged)
    return merged


def save_state(state: dict[str, Any], *, actor: str = "swarm", audit: str | None = None) -> None:
    validate_state(state)
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"
    _atomic_write(path, text)
    if audit:
        _append_audit(actor, audit)


def mark_dogfood(notes: str | None = None) -> dict[str, Any]:
    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()
    phase_0 = state["phase_0"]
    phase_0["decision"] = "DOGFOOD"
    phase_0["selected_mode"] = "plugin"
    phase_0["decided_on"] = today
    phase_0["cohort_run_date"] = None
    phase_0["notes"] = notes or "Initial experiments complete; learn from opt-in plugin dogfooding."
    save_state(state, audit="phase_0.decision=DOGFOOD phase_0.selected_mode=plugin")
    return state


def set_field(path: str, raw_value: str) -> dict[str, Any]:
    state = load_state()
    value = _parse_value(raw_value)
    current: Any = state
    parts = _split_path(path)
    if not parts or any(not part for part in parts):
        raise ValueError("path must be dot-separated, for example phase_1.status")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unknown rollout path: {path}")
        current = current[part]
    leaf = parts[-1]
    if not isinstance(current, dict) or leaf not in current:
        raise ValueError(f"unknown rollout path: {path}")
    current[leaf] = value
    validate_state(state)
    save_state(state, audit=f"{path}={raw_value}")
    return state


def history_lines() -> list[str]:
    path = audit_path()
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def format_status(state: dict[str, Any] | None = None) -> str:
    s = state or load_state()
    phase_0 = s["phase_0"]
    phase_1 = s["phase_1"]
    pattern = s["pattern_5_trial"]
    b1 = s["b1_dispatcher"]
    roles = s["role_promotions"]
    promoted = ", ".join(name for name, data in roles.items() if data.get("primary") == "codex") or "none"
    return "\n".join(
        [
            "Rollout status",
            f"  phase_0: {phase_0['decision']} mode={phase_0['selected_mode']} decided_on={phase_0['decided_on'] or 'n/a'}",
            f"  phase_1: {phase_1['status']}",
            f"  pattern_5_trial: {pattern['status']} decision={pattern['decision']} sampled={pattern['phases_sampled']}",
            f"  b1_dispatcher: {b1['status']}",
            f"  codex primary roles: {promoted}",
        ]
    )


def validate_state(state: dict[str, Any]) -> None:
    _no_unknown(state, TOP_KEYS, "rollout")
    if state.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    phase_0 = _object(state, "phase_0")
    _no_unknown(phase_0, PHASE_0_KEYS, "phase_0")
    _enum(phase_0, "decision", PHASE_0_DECISIONS, "phase_0")
    _enum(phase_0, "selected_mode", PHASE_0_MODES, "phase_0")
    _nullable_string(phase_0, "decided_on", "phase_0")
    _nullable_string(phase_0, "cohort_run_date", "phase_0")
    _string(phase_0, "notes", "phase_0")

    phase_1 = _object(state, "phase_1")
    _no_unknown(phase_1, PHASE_1_KEYS, "phase_1")
    _enum(phase_1, "status", {"pending", "live", "rolled-back"}, "phase_1")
    for key in ("activated_on", "rolled_back_on", "rollback_reason"):
        _nullable_string(phase_1, key, "phase_1")

    pattern = _object(state, "pattern_5_trial")
    _no_unknown(pattern, PATTERN_5_KEYS, "pattern_5_trial")
    _enum(pattern, "status", {"pending", "complete", "abandoned"}, "pattern_5_trial")
    _enum(pattern, "decision", PATTERN_5_DECISIONS, "pattern_5_trial")
    _nullable_string(pattern, "completed_on", "pattern_5_trial")
    if not isinstance(pattern.get("phases_sampled"), int) or pattern["phases_sampled"] < 0:
        raise ValueError("pattern_5_trial.phases_sampled must be a non-negative integer")
    _string(pattern, "notes", "pattern_5_trial")

    b1 = _object(state, "b1_dispatcher")
    _no_unknown(b1, B1_KEYS, "b1_dispatcher")
    _enum(b1, "status", B1_STATUSES, "b1_dispatcher")
    for key in ("shadow_started_on", "live_cutover_on", "rolled_back_on", "notes"):
        if key == "notes":
            _string(b1, key, "b1_dispatcher")
        else:
            _nullable_string(b1, key, "b1_dispatcher")

    roles = _object(state, "role_promotions")
    for role, data in roles.items():
        if not isinstance(data, dict):
            raise ValueError(f"role_promotions.{role} must be an object")
        _no_unknown(data, ROLE_KEYS, f"role_promotions.{role}")
        _enum(data, "primary", BACKENDS, f"role_promotions.{role}")
        _nullable_string(data, "promoted_on", f"role_promotions.{role}")
        _nullable_string(data, "measurement_ref", f"role_promotions.{role}")


def _deep_update(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = deepcopy(value)


def _parse_value(raw: str) -> Any:
    if raw == "null":
        return None
    if raw in {"true", "false"}:
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        return raw


def _split_path(path: str) -> list[str]:
    parts = path.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError("path must be dot-separated, for example phase_1.status")
    if parts[0] == "role_promotions" and len(parts) > 3:
        return ["role_promotions", ".".join(parts[1:-1]), parts[-1]]
    return parts


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _append_audit(actor: str, message: str) -> None:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {actor} {message}\n")


def _object(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _no_unknown(obj: dict[str, Any], allowed: set[str], prefix: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ValueError(f"{prefix}: unknown keys: {', '.join(unknown)}")


def _enum(obj: dict[str, Any], key: str, allowed: set[str], prefix: str) -> None:
    if obj.get(key) not in allowed:
        raise ValueError(f"{prefix}.{key} must be one of {sorted(allowed)}")


def _string(obj: dict[str, Any], key: str, prefix: str) -> None:
    if not isinstance(obj.get(key), str):
        raise ValueError(f"{prefix}.{key} must be a string")


def _nullable_string(obj: dict[str, Any], key: str, prefix: str) -> None:
    if obj.get(key) is not None and not isinstance(obj.get(key), str):
        raise ValueError(f"{prefix}.{key} must be a string or null")
