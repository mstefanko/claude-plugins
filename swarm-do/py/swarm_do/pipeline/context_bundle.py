"""Lazy phase-scoped context bundle renderer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT, resolve_data_dir
from .phase_decisions import render_shared_decisions_markdown, shared_decisions_path
from .phase_sessions import load_phase_sessions, phase_session_path
from .plan import parse_plan_from_text
from .prepare import STATUS_ACCEPTED, check_stale, load_prepared_artifact
from .run_state import _atomic_json_write, append_run_event, utc_now, validate_run_event


SCHEMA_VERSION = 1
DEFAULT_MAX_PROMPT_BYTES = 24_000
UNIT_REQUIRED_ROLES = {"agent-writer", "agent-spec-review"}
KNOWN_ROLES = {"dispatcher", "agent-writer", "agent-spec-review", "agent-review", "agent-docs"}


def render_context_bundle(
    *,
    run_id: str,
    phase_id: str,
    role: str,
    unit_id: str | None = None,
    max_prompt_bytes: int = DEFAULT_MAX_PROMPT_BYTES,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Render one requested phase/role/unit context bundle."""

    if role in UNIT_REQUIRED_ROLES and not unit_id:
        raise ValueError(f"{role} context requires --unit")
    if role not in KNOWN_ROLES:
        raise ValueError(f"unknown context role: {role}")
    if max_prompt_bytes < 500:
        raise ValueError("max_prompt_bytes must be at least 500")

    base = data_dir or resolve_data_dir()
    prepared = load_prepared_artifact(run_id, data_dir=base, repo_root=repo_root)
    if prepared.get("status") != STATUS_ACCEPTED:
        raise ValueError(f"context render requires accepted prepared artifact; got {prepared.get('status')!r}")
    root = _prepared_repo_root(prepared, repo_root=repo_root)
    drift = check_stale(prepared, repo_root=root)
    if drift is not None:
        raise ValueError(f"prepared artifact is stale: {', '.join(drift.reasons)}")

    phase_meta = _phase_meta(prepared, phase_id)
    phase_index = int(phase_meta["phase_index"])
    sidecar_path, sidecar_sha, sidecar = _load_sidecar(prepared, phase_id, repo_root=root)
    unit = _select_unit(sidecar, unit_id) if unit_id else None
    if unit_id and unit is None:
        raise ValueError(f"work unit not found for phase {phase_id}: {unit_id}")

    context_dir = base / "runs" / run_id / "context" / phase_id
    target_dir = context_dir if unit is None else context_dir / "units" / str(unit_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = target_dir / f"{role}.prompt.md"
    context_path = target_dir / f"{role}.context.json"
    decisions_path = context_dir / "decisions.md"
    shared_decisions_md_path = context_dir / "shared-decisions.md"
    previous_handoff_path = context_dir / "previous-handoff.md"
    phase_summary_path = context_dir / "phase-summary.md"
    recovery_context_path, recovery_context_sha, recovery_context_text = _recovery_context(run_id, phase_id, data_dir=base)
    phase_session_mode = phase_session_path(run_id, data_dir=base).is_file() and unit is None

    phase_text, phase_warning = _phase_text(prepared, phase_id, repo_root=root)
    warnings: list[str] = []
    if phase_warning:
        warnings.append(phase_warning)
    if phase_session_mode:
        warnings.append("work_units_informational_phase_session")

    dependency_phase_ids = _dependency_phase_ids(
        prepared=prepared,
        phase_id=phase_id,
        phase_index=phase_index,
        data_dir=base,
        run_id=run_id,
    )
    prior = _prior_handoffs(base, run_id, dependency_phase_ids)
    _write_text_if_changed(previous_handoff_path, _previous_handoff_markdown(prior))
    _write_text_if_changed(decisions_path, _decisions_markdown(prior))
    _write_text_if_changed(
        shared_decisions_md_path,
        render_shared_decisions_markdown(run_id, phase_id=phase_id, data_dir=base),
    )
    _write_text_if_changed(phase_summary_path, _phase_summary_markdown(phase_meta, sidecar, unit))

    if phase_session_mode:
        allowed_files: list[str] = []
        blocked_files: list[str] = []
        context_files: list[str] = []
        acceptance_criteria: list[str] = []
        validation_commands: list[str] = []
    else:
        allowed_files = _strings((unit or {}).get("allowed_files") or (unit or {}).get("files")) or _unit_union(sidecar, "allowed_files", "files")
        blocked_files = _strings((unit or {}).get("blocked_files")) or _unit_union(sidecar, "blocked_files")
        context_files = _strings((unit or {}).get("context_files")) or _unit_union(sidecar, "context_files")
        acceptance_criteria = _strings((unit or {}).get("acceptance_criteria")) or _unit_union(sidecar, "acceptance_criteria")
        validation_commands = _strings((unit or {}).get("validation_commands")) or _unit_union(sidecar, "validation_commands")
    informational_work_units = _informational_work_units(sidecar) if phase_session_mode else []

    source_artifact_path = base / "runs" / run_id / "prepared_plan.v1.json"
    source_list = [
        {"path": _display_path(source_artifact_path), "sha": _sha256_file(source_artifact_path), "kind": "prepared_artifact"},
        {"path": _display_path(root / str(prepared["prepared_plan_path"])), "sha": prepared["prepared_plan_sha"], "kind": "prepared_plan"},
        {"path": _display_path(sidecar_path), "sha": sidecar_sha, "kind": "work_unit_artifact"},
    ]
    for handoff in prior:
        source_list.append({"path": handoff["path"], "sha": handoff["sha"], "kind": "phase_handoff"})
    shared_sidecar_path = shared_decisions_path(run_id, data_dir=base)
    if shared_sidecar_path.is_file():
        source_list.append({"path": _display_path(shared_sidecar_path), "sha": _sha256_file(shared_sidecar_path), "kind": "shared_decisions"})
    if recovery_context_path is not None and recovery_context_sha is not None:
        source_list.append({"path": _display_path(recovery_context_path), "sha": recovery_context_sha, "kind": "phase_recovery_context"})

    prompt = _build_prompt(
        run_id=run_id,
        phase_id=phase_id,
        role=role,
        unit=unit,
        phase_meta=phase_meta,
        phase_text=phase_text,
        allowed_files=allowed_files,
        blocked_files=blocked_files,
        context_files=context_files,
        acceptance_criteria=acceptance_criteria,
        validation_commands=validation_commands,
        source_list=source_list,
        previous_handoff_path=_display_path(previous_handoff_path),
        decisions_path=_display_path(decisions_path),
        shared_decisions_path=_display_path(shared_decisions_md_path),
        recovery_context_path=_display_path(recovery_context_path) if recovery_context_path else None,
        recovery_context_text=recovery_context_text,
        informational_work_units=informational_work_units,
    )
    prompt, truncated = _enforce_prompt_budget(
        prompt,
        phase_text=phase_text,
        max_prompt_bytes=max_prompt_bytes,
        rebuild=lambda excerpt: _build_prompt(
            run_id=run_id,
            phase_id=phase_id,
            role=role,
            unit=unit,
            phase_meta=phase_meta,
            phase_text=excerpt,
            allowed_files=allowed_files,
            blocked_files=blocked_files,
            context_files=context_files,
            acceptance_criteria=acceptance_criteria,
            validation_commands=validation_commands,
            source_list=source_list,
            previous_handoff_path=_display_path(previous_handoff_path),
            decisions_path=_display_path(decisions_path),
            shared_decisions_path=_display_path(shared_decisions_md_path),
            recovery_context_path=_display_path(recovery_context_path) if recovery_context_path else None,
            recovery_context_text=recovery_context_text,
            informational_work_units=informational_work_units,
        ),
    )
    if truncated:
        warnings.append("context_truncated")
    prompt_bytes = len(prompt.encode("utf-8"))

    context = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_index": phase_index,
        "role": role,
        "work_unit_id": unit_id,
        "source_artifact_path": _display_path(source_artifact_path),
        "prepared_plan_sha": prepared["prepared_plan_sha"],
        "phase_content_sha": phase_meta["content_sha"],
        "work_unit_artifact_path": _display_path(sidecar_path),
        "work_unit_artifact_sha": sidecar_sha,
        "allowed_files": allowed_files,
        "blocked_files": blocked_files,
        "context_files": context_files,
        "acceptance_criteria": acceptance_criteria,
        "validation_commands": validation_commands,
        "prior_decisions_path": _display_path(decisions_path),
        "previous_handoff_path": _display_path(previous_handoff_path),
        "shared_decisions_path": _display_path(shared_decisions_md_path),
        "recovery_context_path": _display_path(recovery_context_path) if recovery_context_path else None,
        "recovery_context_sha": recovery_context_sha,
        "source_list": source_list,
        "warnings": sorted(set(warnings)),
        "max_prompt_bytes": max_prompt_bytes,
        "prompt_bytes": prompt_bytes,
        "estimated_tokens": _estimate_tokens(prompt_bytes),
        "rendered_prompt_path": _display_path(prompt_path),
    }
    _validate_context(context)
    _atomic_json_write(context_path, context)
    _write_text_if_changed(prompt_path, prompt)
    _append_context_event(base, context=context, prompt_path=prompt_path, bd_epic_id=_bd_epic_id(prepared))
    return {
        "context": context,
        "context_path": str(context_path),
        "prompt_path": str(prompt_path),
    }


def _phase_meta(prepared: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    for idx, phase in enumerate(prepared.get("phase_map") or []):
        if isinstance(phase, Mapping) and phase.get("phase_id") == phase_id:
            result = dict(phase)
            result["phase_index"] = idx
            return result
    raise ValueError(f"phase not found in prepared artifact: {phase_id}")


def _load_sidecar(prepared: Mapping[str, Any], phase_id: str, *, repo_root: Path) -> tuple[Path, str, dict[str, Any]]:
    descriptor = (prepared.get("work_unit_artifacts") or {}).get(phase_id)
    if not isinstance(descriptor, Mapping):
        raise ValueError(f"work-unit artifact missing for phase: {phase_id}")
    path = repo_root / str(descriptor.get("path") or "")
    if not path.is_file():
        raise FileNotFoundError(f"work-unit artifact missing: {path}")
    sha = _sha256_file(path)
    if sha != descriptor.get("sha"):
        raise ValueError(f"work-unit artifact sha mismatch for phase: {phase_id}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("work-unit artifact root must be an object")
    return path, sha, value


def _select_unit(sidecar: Mapping[str, Any], unit_id: str | None) -> dict[str, Any] | None:
    if not unit_id:
        return None
    for unit in sidecar.get("work_units") or []:
        if isinstance(unit, Mapping) and unit.get("id") == unit_id:
            return dict(unit)
    return None


def _phase_text(prepared: Mapping[str, Any], phase_id: str, *, repo_root: Path) -> tuple[str, str | None]:
    path = repo_root / str(prepared.get("prepared_plan_path") or "")
    if not path.is_file():
        return "", "prepared_plan_missing"
    text = path.read_text(encoding="utf-8")
    for phase in parse_plan_from_text(text):
        if phase.phase_id == phase_id:
            return phase.text.strip(), None
    return "", "phase_text_missing"


def _dependency_phase_ids(
    *,
    prepared: Mapping[str, Any],
    phase_id: str,
    phase_index: int,
    data_dir: Path,
    run_id: str,
) -> list[str]:
    state_path = phase_session_path(run_id, data_dir=data_dir)
    if state_path.is_file():
        try:
            state = load_phase_sessions(run_id, data_dir=data_dir)
        except Exception:
            state = {}
        for phase in state.get("phases") or []:
            if isinstance(phase, Mapping) and phase.get("phase_id") == phase_id:
                return _strings(phase.get("depends_on_phase_ids"))
    for phase in prepared.get("phase_map") or []:
        if not isinstance(phase, Mapping) or phase.get("phase_id") != phase_id:
            continue
        if isinstance(phase.get("depends_on_phase_ids"), list):
            return _strings(phase.get("depends_on_phase_ids"))
        break
    if phase_index <= 0:
        return []
    phase_map = prepared.get("phase_map") or []
    if phase_index - 1 < len(phase_map) and isinstance(phase_map[phase_index - 1], Mapping):
        return [str(phase_map[phase_index - 1].get("phase_id"))]
    return []


def _prior_handoffs(base: Path, run_id: str, phase_ids: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for prior_phase_id in phase_ids:
        handoff_dir = base / "runs" / run_id / "phase_handoffs" / prior_phase_id
        candidates = sorted(handoff_dir.glob("attempt-*.handoff.json"), key=_handoff_attempt)
        if not candidates:
            continue
        path = candidates[-1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("status") != "complete":
            continue
        results.append(
            {
                "phase_id": prior_phase_id,
                "path": _display_path(path),
                "sha": _sha256_file(path),
                "summary": str(payload.get("summary") or ""),
                "decisions": _strings(payload.get("decisions")),
                "next_phase_context": _strings(payload.get("next_phase_context")),
            }
        )
    return results


def _recovery_context(base_run_id: str, phase_id: str, *, data_dir: Path) -> tuple[Path | None, str | None, str | None]:
    state_path = phase_session_path(base_run_id, data_dir=data_dir)
    if not state_path.is_file():
        return None, None, None
    try:
        state = load_phase_sessions(base_run_id, data_dir=data_dir)
    except Exception:
        return None, None, None
    for phase in state.get("phases") or []:
        if not isinstance(phase, Mapping) or phase.get("phase_id") != phase_id:
            continue
        if phase.get("status") != "pending" or int(phase.get("attempt") or 0) <= 0:
            return None, None, None
        path_value = phase.get("recovery_context_path")
        if not isinstance(path_value, str):
            history = [item for item in phase.get("attempt_history") or [] if isinstance(item, Mapping)]
            for item in reversed(history):
                if isinstance(item.get("recovery_context_path"), str):
                    path_value = str(item["recovery_context_path"])
                    break
        if not isinstance(path_value, str):
            return None, None, None
        path = Path(path_value)
        if not path.is_absolute():
            candidates = [REPO_ROOT / path, data_dir / path]
            path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        if not path.is_file():
            return None, None, None
        text = path.read_text(encoding="utf-8", errors="replace")
        return path, _sha256_file(path), _truncate_utf8(text, 6000)
    return None, None, None


def _handoff_attempt(path: Path) -> int:
    match = re.match(r"attempt-(\d+)\.handoff\.json$", path.name)
    return int(match.group(1)) if match else -1


def _previous_handoff_markdown(prior: list[dict[str, Any]]) -> str:
    if not prior:
        return "No previous phase handoff.\n"
    chunks: list[str] = ["# Previous Phase Handoffs"]
    for item in prior:
        chunks.append(f"\n## Phase {item['phase_id']}")
        chunks.append(item["summary"] or "(no summary)")
        next_context = item.get("next_phase_context") or []
        if next_context:
            chunks.append("\nNext phase context:")
            chunks.extend(f"- {line}" for line in next_context)
    return "\n".join(chunks).rstrip() + "\n"


def _decisions_markdown(prior: list[dict[str, Any]]) -> str:
    items_with_decisions = [
        item for item in prior if item.get("decisions")
    ]
    if not items_with_decisions:
        return "No prior decisions.\n"
    chunks = ["# Prior Decisions"]
    for item in items_with_decisions:
        chunks.append(f"\n## Phase {item['phase_id']}")
        chunks.extend(f"- {line}" for line in item.get("decisions") or [])
    return "\n".join(chunks).rstrip() + "\n"


def _phase_summary_markdown(
    phase: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    unit: Mapping[str, Any] | None,
) -> str:
    lines = [
        f"# Phase {phase.get('phase_id')}: {phase.get('title')}",
        f"- complexity: {phase.get('complexity')}",
        f"- kind: {phase.get('kind')}",
        f"- work_units: {len(sidecar.get('work_units') or [])}",
    ]
    if unit is not None:
        lines.append(f"- selected_unit: {unit.get('id')} - {unit.get('title')}")
    return "\n".join(lines) + "\n"


def _build_prompt(
    *,
    run_id: str,
    phase_id: str,
    role: str,
    unit: Mapping[str, Any] | None,
    phase_meta: Mapping[str, Any],
    phase_text: str,
    allowed_files: list[str],
    blocked_files: list[str],
    context_files: list[str],
    acceptance_criteria: list[str],
    validation_commands: list[str],
    source_list: list[dict[str, Any]],
    previous_handoff_path: str,
    decisions_path: str,
    shared_decisions_path: str,
    recovery_context_path: str | None,
    recovery_context_text: str | None,
    informational_work_units: list[str],
) -> str:
    lines = [
        f"# SwarmDaddy Phase Context: {role}",
        "",
        f"- run_id: {run_id}",
        f"- phase_id: {phase_id}",
        f"- phase_index: {phase_meta.get('phase_index')}",
        f"- phase_title: {phase_meta.get('title')}",
    ]
    if unit is not None:
        lines.extend(
            [
                f"- work_unit_id: {unit.get('id')}",
                f"- work_unit_title: {unit.get('title')}",
                f"- work_unit_goal: {unit.get('goal')}",
            ]
        )
    lines.extend(
        [
            "",
            "## Boundaries",
            _list_block("Allowed files", allowed_files),
            _list_block("Blocked files", blocked_files),
            _list_block("Context files", context_files),
            "",
            "## Acceptance",
            _list_block("Acceptance criteria", acceptance_criteria),
            _list_block("Validation commands", validation_commands),
            "",
            "## Prior Phase Artifacts",
            f"- previous_handoff_path: {previous_handoff_path}",
            f"- prior_decisions_path: {decisions_path}",
            f"- shared_decisions_path: {shared_decisions_path}",
        "",
        "## Source Artifacts",
        ]
    )
    lines.extend(f"- {item['kind']}: {item['path']} sha={item['sha']}" for item in source_list)
    if recovery_context_path and recovery_context_text:
        lines.extend(
            [
                "",
                "## Recovery Context",
                f"- recovery_context_path: {recovery_context_path}",
                "",
                recovery_context_text.rstrip(),
            ]
        )
    if informational_work_units:
        lines.extend(["", "## Informational Decomposition"])
        lines.append("Phase sessions execute this whole phase. These prepared work units are context only:")
        lines.extend(f"- {line}" for line in informational_work_units)
    lines.extend(["", "## Phase Text", phase_text or "(phase text unavailable)", ""])
    if unit is not None and unit.get("handoff_notes"):
        lines.extend(["## Unit Handoff Notes", str(unit.get("handoff_notes")), ""])
    return "\n".join(lines).rstrip() + "\n"


def _list_block(label: str, values: list[str]) -> str:
    if not values:
        return f"{label}: none"
    return label + ":\n" + "\n".join(f"- {value}" for value in values)


def _enforce_prompt_budget(
    prompt: str,
    *,
    phase_text: str,
    max_prompt_bytes: int,
    rebuild: Any,
) -> tuple[str, bool]:
    if len(prompt.encode("utf-8")) <= max_prompt_bytes:
        return prompt, False
    shell = rebuild("")
    shell_bytes = len(shell.encode("utf-8"))
    available = max(0, max_prompt_bytes - shell_bytes - 300)
    excerpt = _truncate_utf8(phase_text, available)
    if excerpt and excerpt != phase_text:
        excerpt = excerpt.rstrip() + "\n\n[context_truncated]"
    rebuilt = rebuild(excerpt)
    if len(rebuilt.encode("utf-8")) > max_prompt_bytes:
        rebuilt = _truncate_utf8(rebuilt, max_prompt_bytes)
    return rebuilt, True


def _truncate_utf8(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    return data[:max_bytes].decode("utf-8", errors="ignore")


def _unit_union(sidecar: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for unit in sidecar.get("work_units") or []:
        if not isinstance(unit, Mapping):
            continue
        for key in keys:
            for value in _strings(unit.get(key)):
                if value not in values:
                    values.append(value)
    return values


def _informational_work_units(sidecar: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for unit in sidecar.get("work_units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = unit.get("id")
        title = unit.get("title") or unit.get("goal") or ""
        if isinstance(unit_id, str) and unit_id:
            values.append(f"{unit_id}: {title}".rstrip(": "))
    return values


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _prepared_repo_root(prepared: Mapping[str, Any], *, repo_root: Path | None) -> Path:
    return (Path(repo_root) if repo_root is not None else Path(str(prepared.get("repo_root") or REPO_ROOT))).resolve(strict=False)


def _estimate_tokens(prompt_bytes: int) -> int:
    return max(1, (prompt_bytes + 3) // 4)


def _validate_context(context: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import validate_value

    schema = json.loads((REPO_ROOT / "schemas" / "phase_context.schema.json").read_text(encoding="utf-8"))
    errors = validate_value(dict(context), schema)
    if errors:
        raise ValueError("phase context schema invalid: " + "; ".join(errors))


def _append_context_event(base: Path, *, context: Mapping[str, Any], prompt_path: Path, bd_epic_id: str | None) -> None:
    row = {
        "run_id": context["run_id"],
        "timestamp": utc_now(),
        "event_type": "phase_context_rendered",
        "bd_epic_id": bd_epic_id,
        "phase_id": context["phase_id"],
        "work_unit_id": context.get("work_unit_id"),
        "child_bead_ids": None,
        "reason": None,
        "retry_count": None,
        "handoff_count": None,
        "integration_branch_head": None,
        "details": {
            "phase_index": context["phase_index"],
            "role": context["role"],
            "prompt_path": _display_path(prompt_path),
            "prompt_bytes": context["prompt_bytes"],
            "estimated_tokens": context["estimated_tokens"],
            "warnings": context["warnings"],
        },
        "schema_ok": True,
    }
    validate_run_event(row)
    append_run_event(base, row)


def _write_text_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve(strict=False)))
    except ValueError:
        return str(path)


def _bd_epic_id(prepared: Mapping[str, Any]) -> str | None:
    value = prepared.get("bd_epic_id")
    return value if isinstance(value, str) else None


__all__ = ["render_context_bundle"]
