"""Work-unit artifact producer for plan-prepare.

Heading recognition (Tier 1+2 fixes):

- ``_acceptance_criteria`` matches any heading level (``#`` through ``######``)
  or a bold-wrapped line (``**Acceptance Criteria**``) — case-insensitive.
- ``_validation_commands`` matches both ``Verification`` and
  ``Validation Commands`` aliases under any heading prefix and captures the
  contents of the first fenced code block, stopping at ``Expected Results``
  or the next heading.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .plan import ParsedPhase, inspect_phase, parse_plan
from .validation import LintResult, schema_lint_work_units


AgentRunner = Callable[[ParsedPhase, Mapping[str, Any], list[str]], Mapping[str, Any]]


@dataclass(frozen=True)
class DecomposeResult:
    artifact: dict[str, Any]
    lint: LintResult
    retry_count: int
    escalated: bool
    rejected_path: str | None = None


def decompose_phase(
    phase: ParsedPhase,
    *,
    plan_path: str | Path | None = None,
    bd_epic_id: str | None = None,
    write_to: str | Path | None = None,
    agent_runner: AgentRunner | None = None,
    allow_rejected: bool = False,
    max_units: int = 8,
) -> DecomposeResult:
    """Produce and lint a ``work_units.v2`` artifact for one phase.

    The default path is deterministic. Tests or a dispatcher shim can provide
    ``agent_runner`` to exercise the single-retry contract for model-produced
    artifacts.
    """

    report = inspect_phase(phase)
    if report.complexity == "simple" or agent_runner is None:
        artifact = synthesize_work_units(phase, plan_path=plan_path, bd_epic_id=bd_epic_id, max_units=max_units)
        lint = schema_lint_work_units(artifact)
        _write_if_requested(write_to, artifact)
        return DecomposeResult(artifact, lint, 0, bool(lint.errors), None)

    artifact = _normalize_agent_artifact(agent_runner(phase, report.to_dict(), []), phase, plan_path, bd_epic_id)
    lint = schema_lint_work_units(artifact)
    if not lint.errors:
        _write_if_requested(write_to, artifact)
        return DecomposeResult(artifact, lint, 0, False, None)

    retry_artifact = _normalize_agent_artifact(agent_runner(phase, report.to_dict(), lint.errors), phase, plan_path, bd_epic_id)
    retry_lint = schema_lint_work_units(retry_artifact)
    if not retry_lint.errors:
        _write_if_requested(write_to, retry_artifact)
        return DecomposeResult(retry_artifact, retry_lint, 1, False, None)

    rejected_path = None
    if write_to is not None:
        rejected = Path(write_to).with_suffix(".rejected.json")
        rejected.parent.mkdir(parents=True, exist_ok=True)
        rejected.write_text(json.dumps(retry_artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rejected_path = str(rejected)
        if allow_rejected:
            _write_if_requested(write_to, retry_artifact)
    return DecomposeResult(retry_artifact, retry_lint, 1, True, rejected_path)


def decompose_plan_phase(
    plan_path: str | Path,
    phase_id: str,
    *,
    write_to: str | Path | None = None,
    bd_epic_id: str | None = None,
    allow_rejected: bool = False,
) -> DecomposeResult:
    phases = [phase for phase in parse_plan(plan_path) if phase.phase_id == phase_id]
    if not phases:
        raise ValueError(f"phase not found: {phase_id}")
    return decompose_phase(
        phases[0],
        plan_path=plan_path,
        bd_epic_id=bd_epic_id,
        write_to=write_to,
        allow_rejected=allow_rejected,
    )


def synthesize_work_units(
    phase: ParsedPhase,
    *,
    plan_path: str | Path | None = None,
    bd_epic_id: str | None = None,
    max_units: int = 8,
) -> dict[str, Any]:
    report = inspect_phase(phase)
    files = report.file_paths or ["."]
    plans = _semantic_unit_plans(phase, files, max_units=max_units) if report.complexity != "simple" else [
        {"files": files, "category": "phase", "acceptance_criteria": _acceptance_criteria(phase), "serial_key": None}
    ]
    units: list[dict[str, Any]] = []
    for idx, plan in enumerate(plans, 1):
        unit_id = _unit_id(phase.phase_id, idx, len(plans))
        units.append(
            _unit(
                unit_id,
                phase,
                list(plan["files"]),
                idx,
                len(plans),
                depends_on=[],
                category=str(plan.get("category") or "phase"),
                acceptance_criteria=list(plan.get("acceptance_criteria") or _acceptance_criteria(phase)),
            )
        )
    _assign_semantic_dependencies(units, plans)
    return {
        "schema_version": 2,
        "plan_path": str(plan_path) if plan_path is not None else None,
        "bd_epic_id": bd_epic_id,
        "work_units": units,
    }


def _unit(
    unit_id: str,
    phase: ParsedPhase,
    files: list[str],
    idx: int,
    total: int,
    *,
    depends_on: list[str],
    category: str = "phase",
    acceptance_criteria: list[str] | None = None,
) -> dict[str, Any]:
    title_suffix = "" if total == 1 else f" ({idx}/{total})"
    return {
        "id": unit_id,
        "title": f"{phase.title}{title_suffix}",
        "goal": _goal(phase, files, idx, total, category=category),
        "depends_on": depends_on,
        "context_files": _context_files(phase, files),
        "allowed_files": files,
        "blocked_files": [],
        "acceptance_criteria": acceptance_criteria or _acceptance_criteria(phase),
        "validation_commands": _validation_commands(phase),
        "expected_results": ["commands exit 0 or produce the documented approval output"],
        "risk_tags": _risk_tags(phase),
        "handoff_notes": "",
        "beads_id": None,
        "worktree_branch": None,
        "status": "pending",
        "failure_reason": None,
        "retry_count": 0,
        "handoff_count": 0,
    }


def _normalize_agent_artifact(
    artifact: Mapping[str, Any],
    phase: ParsedPhase,
    plan_path: str | Path | None,
    bd_epic_id: str | None,
) -> dict[str, Any]:
    value = dict(artifact)
    value.setdefault("schema_version", 2)
    value.setdefault("plan_path", str(plan_path) if plan_path is not None else None)
    value.setdefault("bd_epic_id", bd_epic_id)
    units = value.get("work_units")
    if not isinstance(units, list):
        value["work_units"] = []
        return value
    normalized = []
    for idx, unit_value in enumerate(units, 1):
        if not isinstance(unit_value, Mapping):
            continue
        unit = dict(unit_value)
        unit.setdefault("id", _unit_id(phase.phase_id, idx, len(units)))
        unit.setdefault("title", str(unit["id"]))
        unit.setdefault("goal", phase.title)
        unit.setdefault("depends_on", [])
        unit.setdefault("context_files", [])
        if "allowed_files" not in unit and "files" not in unit:
            unit["allowed_files"] = inspect_phase(phase).file_paths or ["."]
        unit.setdefault("blocked_files", [])
        unit.setdefault("acceptance_criteria", _acceptance_criteria(phase))
        unit.setdefault("validation_commands", [])
        unit.setdefault("expected_results", [])
        unit.setdefault("risk_tags", [])
        unit.setdefault("handoff_notes", "")
        unit.setdefault("beads_id", None)
        unit.setdefault("worktree_branch", None)
        unit.setdefault("status", "pending")
        unit.setdefault("failure_reason", None)
        unit.setdefault("retry_count", 0)
        unit.setdefault("handoff_count", 0)
        normalized.append(unit)
    value["work_units"] = normalized
    return value


def _file_groups(files: list[str], *, max_units: int) -> list[list[str]]:
    if len(files) <= 1:
        return [files]
    groups: dict[str, list[str]] = {}
    for path in files:
        prefix = path.split("/", 1)[0] if "/" in path else "."
        groups.setdefault(prefix, []).append(path)
    values = list(groups.values())
    if len(values) > max_units:
        chunked: list[list[str]] = []
        for idx in range(max_units):
            chunked.append([])
        for idx, path in enumerate(files):
            chunked[idx % max_units].append(path)
        values = [group for group in chunked if group]
    return values


def _semantic_unit_plans(phase: ParsedPhase, files: list[str], *, max_units: int) -> list[dict[str, Any]]:
    criteria = _acceptance_criteria(phase)
    action_map = _file_action_map(phase)
    buckets: dict[tuple[str, str], list[str]] = {}
    for path in files:
        category = _semantic_category(path)
        action = action_map.get(path, "")
        buckets.setdefault((category, action), []).append(path)

    plans: list[dict[str, Any]] = []
    for (category, action), bucket_files in buckets.items():
        max_files = _max_files_for_budget(criteria)
        for file_chunk in _chunks(bucket_files, max_files):
            selected = _criteria_for_group(criteria, file_chunk, category)
            serial_key = None
            if len(selected) > 5:
                serial_key = f"criteria:{category}:{','.join(file_chunk)}"
                for criteria_chunk in _chunks(selected, 5):
                    plans.append(
                        {
                            "files": file_chunk,
                            "category": category,
                            "action": action,
                            "acceptance_criteria": criteria_chunk,
                            "serial_key": serial_key,
                        }
                    )
            else:
                plans.append(
                    {
                        "files": file_chunk,
                        "category": category,
                        "action": action,
                        "acceptance_criteria": selected,
                        "serial_key": serial_key,
                    }
                )

    if not plans:
        return [{"files": files or ["."], "category": "phase", "acceptance_criteria": criteria, "serial_key": None}]
    if len(plans) > max_units:
        return _merge_tail_plans(plans, max_units)
    return plans


def _assign_semantic_dependencies(units: list[dict[str, Any]], plans: list[dict[str, Any]]) -> None:
    category_ids: dict[str, list[str]] = {}
    serial_previous: dict[str, str] = {}
    previous_for_file: dict[str, str] = {}
    for unit, plan in zip(units, plans):
        category_ids.setdefault(str(plan.get("category") or "phase"), []).append(unit["id"])

    for unit, plan in zip(units, plans):
        deps: set[str] = set()
        serial_key = plan.get("serial_key")
        if isinstance(serial_key, str):
            previous = serial_previous.get(serial_key)
            if previous:
                deps.add(previous)
            serial_previous[serial_key] = unit["id"]

        category = str(plan.get("category") or "phase")
        category_parts = set(category.split("+"))
        if "cli" in category_parts:
            for dependency_category in ("parser", "schema", "orchestration"):
                deps.update(category_ids.get(dependency_category, []))
        elif "tests" in category_parts:
            for dependency_category, ids in category_ids.items():
                dependency_parts = set(dependency_category.split("+"))
                if dependency_parts.isdisjoint({"tests", "docs"}):
                    deps.update(ids)

        for path in unit.get("allowed_files", []):
            for previous_path, previous in previous_for_file.items():
                if _path_scopes_overlap(path, previous_path):
                    deps.add(previous)
            previous_for_file[path] = unit["id"]
        deps.discard(unit["id"])
        unit["depends_on"] = sorted(deps)


def _semantic_category(path: str) -> str:
    lowered = path.lower()
    name = Path(path).name.lower()
    if lowered.startswith(("docs/", "readme")) or name.endswith(".md"):
        return "docs"
    if lowered.startswith(("commands/", "bin/")) or name == "cli.py":
        return "cli"
    if "/tests/" in lowered or lowered.endswith("/tests") or lowered.startswith("tests/") or name in {"tests"} or name.startswith("test_"):
        return "tests"
    if lowered.startswith("schemas/") or name in {"validation.py"}:
        return "schema"
    if name in {"plan.py", "decompose.py"} or any(token in lowered for token in ("parser", "grammar", "lint")):
        return "parser"
    if name in {"prepare.py", "run_state.py", "resume.py", "executor.py", "work_units.py", "worktrees.py"}:
        return "orchestration"
    if lowered.startswith(("role-specs/", "agents/", "roles/", "permissions/")):
        return "roles"
    if "/tui/" in lowered or lowered.startswith("py/swarm_do/tui/"):
        return "tui"
    parent = str(Path(path).parent)
    return parent if parent != "." else "phase"


def _path_scopes_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    left_norm = left.rstrip("/")
    right_norm = right.rstrip("/")
    return left_norm.startswith(right_norm + "/") or right_norm.startswith(left_norm + "/")


def _file_action_map(phase: ParsedPhase) -> dict[str, str]:
    actions: dict[str, str] = {}
    for line in phase.text.splitlines():
        paths = re.findall(r"`([^`\n]+)`", line)
        if not paths:
            continue
        lowered = line.lower()
        action = ""
        for candidate in ("create", "add", "extend", "modify", "update", "test", "delete"):
            if candidate in lowered:
                action = candidate
                break
        if not action:
            continue
        for path in paths:
            actions[path] = action
    return actions


def _max_files_for_budget(criteria: list[str]) -> int:
    criteria_count = min(len(criteria), 5)
    return max(1, (40 - 8 - (2 * criteria_count)) // 4)


def _criteria_for_group(criteria: list[str], files: list[str], category: str) -> list[str]:
    if not criteria:
        return ["Phase objective is implemented for the allowed file scope."]
    tokens = {category.lower()}
    for path in files:
        p = Path(path)
        tokens.add(path.lower())
        tokens.add(p.name.lower())
        if p.stem:
            tokens.add(p.stem.lower())
    selected = [
        criterion
        for criterion in criteria
        if any(token and token in criterion.lower() for token in tokens)
    ]
    return selected or list(criteria)


def _chunks(values: list[Any], size: int) -> list[list[Any]]:
    return [values[idx : idx + max(1, size)] for idx in range(0, len(values), max(1, size))]


def _merge_tail_plans(plans: list[dict[str, Any]], max_units: int) -> list[dict[str, Any]]:
    if max_units < 1 or len(plans) <= max_units:
        return plans
    head = [dict(plan) for plan in plans[: max_units - 1]]
    tail_files: list[str] = []
    tail_criteria: list[str] = []
    tail_categories: list[str] = []
    for plan in plans[max_units - 1 :]:
        tail_files.extend(str(path) for path in plan.get("files", []))
        tail_criteria.extend(str(item) for item in plan.get("acceptance_criteria", []))
        tail_categories.append(str(plan.get("category") or "phase"))
    head.append(
        {
            "files": list(dict.fromkeys(tail_files)),
            "category": "+".join(sorted(set(tail_categories))) or "phase",
            "acceptance_criteria": list(dict.fromkeys(tail_criteria)) or ["Phase objective is implemented."],
            "serial_key": None,
        }
    )
    return head


def _unit_id(phase_id: str, idx: int, total: int) -> str:
    stem = re.sub(r"[^a-z0-9-]+", "-", phase_id.lower()).strip("-") or "phase"
    return f"unit-{stem}" if total == 1 else f"unit-{stem}-{idx}"


def _goal(phase: ParsedPhase, files: list[str], idx: int, total: int, *, category: str = "phase") -> str:
    if total == 1:
        return f"Implement phase {phase.phase_id}: {phase.title}."
    return f"Implement phase {phase.phase_id} {category} slice {idx}/{total} for {', '.join(files)}."


def _context_files(phase: ParsedPhase, files: list[str]) -> list[str]:
    context = [path for path in phase.referenced_files if path not in files]
    return context[:8]


_AC_HEADING_RE = re.compile(r"^(?:#{1,6}\s+|\*\*)?acceptance criteria", re.IGNORECASE)
_NEXT_HEADING_RE = re.compile(r"^(?:#{1,6}\s+|\*\*)\S")


def _acceptance_criteria(phase: ParsedPhase) -> list[str]:
    lines: list[str] = []
    capture = False
    for raw in phase.text.splitlines():
        stripped = raw.strip()
        if not capture:
            if _AC_HEADING_RE.match(stripped):
                capture = True
            continue
        if _NEXT_HEADING_RE.match(stripped) and not _AC_HEADING_RE.match(stripped):
            break
        if re.match(r"\s*[-*+]\s+", raw):
            lines.append(re.sub(r"^\s*[-*+]\s+", "", raw).strip())
    if lines:
        return lines
    return [f"Phase {phase.phase_id} objective is implemented for the allowed file scope."]


_VC_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+|\*\*)?(?:verification|validation)\s+commands?",
    re.IGNORECASE,
)
_EXPECTED_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+|\*\*)?expected\s+results?",
    re.IGNORECASE,
)


def _validation_commands(phase: ParsedPhase) -> list[str]:
    commands: list[str] = []
    capture = False
    in_fence = False
    for line in phase.text.splitlines():
        stripped = line.strip()
        if not capture:
            if _VC_HEADING_RE.match(stripped):
                capture = True
            continue
        # When inside a fenced block, capture the command lines verbatim;
        # the fence delimiters themselves are skipped.
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            if stripped:
                commands.append(stripped.strip("-*` "))
            continue
        # Outside a fence: stop on the next heading or Expected results.
        if _EXPECTED_HEADING_RE.match(stripped):
            break
        if _NEXT_HEADING_RE.match(stripped) and not _VC_HEADING_RE.match(stripped):
            break
        if stripped:
            commands.append(stripped.strip("-*` "))
    return [
        command
        for command in commands
        if command and not command.lower().startswith("expected results")
    ][:8]


def _risk_tags(phase: ParsedPhase) -> list[str]:
    lower = phase.text.lower()
    tags = []
    for keyword in ("security", "migration", "parser", "schema", "telemetry", "dispatcher", "budget"):
        if keyword in lower:
            tags.append(keyword)
    return tags


def _write_if_requested(path: str | Path | None, artifact: Mapping[str, Any]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


_BULLET_RE = re.compile(r"^\s*[-*+]\s+")


def build_decompose_diagnostic(
    phase: ParsedPhase,
    result: DecomposeResult,
    *,
    plan_path: str | Path | None = None,
    max_units: int = 8,
) -> dict[str, Any]:
    """Snapshot of decomposition inputs and decisions for telemetry.

    Returns a JSON-serializable dict suitable for embedding in an
    observations.jsonl row with ``event_type='decompose_diagnostic'``. Pure
    data — does no I/O. Callers stamp ``run_id`` / ``phase_id`` / timestamps
    when writing the row.
    """

    report = inspect_phase(phase)
    files = report.file_paths or ["."]
    bullet_count = sum(1 for line in phase.text.splitlines() if _BULLET_RE.match(line))
    cluster_signals = sorted({_semantic_category(path) for path in files})

    if report.complexity == "simple":
        split_decision = "single"
    elif len(cluster_signals) > max_units:
        split_decision = "semantic-merge-capped"
    else:
        split_decision = "split-by-semantic-cluster"

    units = result.artifact.get("work_units", []) or []
    depends_on = [
        {
            "unit_id": unit.get("id"),
            "depends_on": list(unit.get("depends_on", []) or []),
        }
        for unit in units
        if isinstance(unit, Mapping)
    ]

    lint = result.lint
    return {
        "phase_id": phase.phase_id,
        "plan_path": str(plan_path) if plan_path is not None else None,
        "complexity": report.complexity,
        "bullet_count": bullet_count,
        "file_count": len(files),
        "directory_count": len(cluster_signals),
        "cluster_signals": cluster_signals,
        "split_decision": split_decision,
        "max_units": max_units,
        "unit_count": len(units),
        "depends_on": depends_on,
        "retry_count": result.retry_count,
        "escalated": result.escalated,
        "rejected_path": result.rejected_path,
        "lint_error_count": len(lint.errors) if lint else 0,
        "lint_warning_count": len(lint.warnings) if lint else 0,
    }
