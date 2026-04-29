"""Lazy phase-scoped context bundle renderer."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT, resolve_data_dir
from .phase_sessions import PhaseSessionError
from .plan import parse_plan_from_text
from .prepare import STATUS_ACCEPTED, check_stale, load_prepared_artifact
from .run_state import append_run_event, utc_now


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
    previous_handoff_path = context_dir / "previous-handoff.md"
    phase_summary_path = context_dir / "phase-summary.md"

    phase_text, phase_warning = _phase_text(prepared, phase_id, repo_root=root)
    warnings: list[str] = []
    if phase_warning:
        warnings.append(phase_warning)

    prior = _prior_handoffs(base, run_id, prepared, phase_index)
    _write_text_if_changed(previous_handoff_path, _previous_handoff_markdown(prior))
    _write_text_if_changed(decisions_path, _decisions_markdown(prior))
    _write_text_if_changed(phase_summary_path, _phase_summary_markdown(phase_meta, sidecar, unit))

    allowed_files = _strings((unit or {}).get("allowed_files") or (unit or {}).get("files")) or _unit_union(sidecar, "allowed_files", "files")
    blocked_files = _strings((unit or {}).get("blocked_files")) or _unit_union(sidecar, "blocked_files")
    context_files = _strings((unit or {}).get("context_files")) or _unit_union(sidecar, "context_files")
    acceptance_criteria = _strings((unit or {}).get("acceptance_criteria")) or _unit_union(sidecar, "acceptance_criteria")
    validation_commands = _strings((unit or {}).get("validation_commands")) or _unit_union(sidecar, "validation_commands")

    source_artifact_path = base / "runs" / run_id / "prepared_plan.v1.json"
    source_list = [
        {"path": _display_path(source_artifact_path), "sha": _sha256_file(source_artifact_path), "kind": "prepared_artifact"},
        {"path": _display_path(root / str(prepared["prepared_plan_path"])), "sha": prepared["prepared_plan_sha"], "kind": "prepared_plan"},
        {"path": _display_path(sidecar_path), "sha": sidecar_sha, "kind": "work_unit_artifact"},
    ]
    for handoff in prior:
        source_list.append({"path": handoff["path"], "sha": handoff["sha"], "kind": "phase_handoff"})

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


def _prior_handoffs(base: Path, run_id: str, prepared: Mapping[str, Any], phase_index: int) -> list[dict[str, Any]]:
    phase_ids = [
        str(phase.get("phase_id"))
        for idx, phase in enumerate(prepared.get("phase_map") or [])
        if idx < phase_index and isinstance(phase, Mapping)
    ]
    results: list[dict[str, Any]] = []
    for prior_phase_id in phase_ids:
        handoff_dir = base / "runs" / run_id / "phase_handoffs" / prior_phase_id
        candidates = sorted(handoff_dir.glob("attempt-*.handoff.json"))
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
    decisions: list[str] = []
    for item in prior:
        decisions.extend(str(line) for line in item.get("decisions") or [])
    if not decisions:
        return "No prior decisions.\n"
    return "# Prior Decisions\n\n" + "\n".join(f"- {line}" for line in decisions) + "\n"


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
            "",
            "## Source Artifacts",
        ]
    )
    lines.extend(f"- {item['kind']}: {item['path']} sha={item['sha']}" for item in source_list)
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
        raise PhaseSessionError("phase context schema invalid: " + "; ".join(errors))


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
    _validate_run_event(row)
    append_run_event(base, row)


def _validate_run_event(row: Mapping[str, Any]) -> None:
    from swarm_do.telemetry.schemas import load_schema, validate_value

    errors = validate_value(dict(row), load_schema("run_events"))
    if errors:
        raise PhaseSessionError("run_event schema invalid: " + "; ".join(errors))


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        tmp.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
        raise


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
