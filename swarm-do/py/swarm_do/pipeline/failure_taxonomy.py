"""Shared failure-kind taxonomy for durable phase sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CATEGORIES = (
    "artifact",
    "artifact_contract",
    "child_result",
    "environment",
    "launcher",
    "lifecycle",
    "operator",
    "permission",
    "writer_runtime",
)

RETRY_CLASSES = (
    "adopt",
    "retry",
    "recovery_retry",
    "human_gate",
    "terminal",
    "child_controlled",
)


@dataclass(frozen=True)
class FailureKindSpec:
    kind: str
    category: str
    retry_class: str
    operator_title: str
    operator_message: str
    required_evidence: tuple[str, ...]
    examples: tuple[str, ...] = ()
    deprecated: bool = False
    aliases: tuple[str, ...] = ()


_UNKNOWN_CHILD_RESULT = FailureKindSpec(
    kind="child_result_unknown",
    category="child_result",
    retry_class="child_controlled",
    operator_title="Child-reported failure",
    operator_message=(
        "The child result reported a failure kind SwarmDaddy does not own. "
        "Use the child result and handoff fields to decide retryability."
    ),
    required_evidence=("child_result",),
)


_SPECS = (
    FailureKindSpec(
        "adoptable_artifacts",
        "artifact",
        "adopt",
        "Valid artifacts can be adopted",
        "Valid result and handoff artifacts exist, so SwarmDaddy can adopt the attempt.",
        ("valid_result_artifact", "valid_handoff_artifact"),
    ),
    FailureKindSpec(
        "launcher_nonzero_with_artifacts",
        "launcher",
        "adopt",
        "Launcher exited non-zero after artifacts",
        "The launcher returned non-zero, but valid result and handoff artifacts are available for adoption.",
        ("launcher_result", "returncode", "valid_result_artifact", "valid_handoff_artifact"),
    ),
    FailureKindSpec(
        "partial_artifacts_invalid",
        "artifact_contract",
        "recovery_retry",
        "Partial artifacts failed contract validation",
        "Some attempt artifacts were present but failed the phase artifact contract. Recovery can retry unless the error is deterministic.",
        ("artifact_contract_errors", "launch_dir"),
    ),
    FailureKindSpec(
        "lease_expired_no_artifacts",
        "lifecycle",
        "retry",
        "Lease expired before artifacts",
        "The phase lease expired and no valid result and handoff artifacts were available. SwarmDaddy can retry within budget.",
        ("launch_dir", "lease_ttl"),
    ),
    FailureKindSpec(
        "child_process_dead_no_artifacts",
        "lifecycle",
        "retry",
        "Child process ended before artifacts",
        "The same-host child process is no longer alive and no valid artifacts were available. SwarmDaddy can retry within budget.",
        ("child_liveness", "launch_dir"),
    ),
    FailureKindSpec(
        "launcher_nonzero_no_artifacts",
        "launcher",
        "retry",
        "Launcher exited before artifacts",
        "The launcher exited non-zero before valid result and handoff artifacts were available. SwarmDaddy can retry within budget.",
        ("launcher_result", "returncode", "launch_dir"),
    ),
    FailureKindSpec(
        "outer_json_missing_no_artifacts",
        "launcher",
        "retry",
        "Launcher produced no outer JSON",
        "No parseable launcher JSON was found and no valid artifacts were available. SwarmDaddy can retry within budget.",
        ("stdout_or_outer_json", "launch_dir"),
    ),
    FailureKindSpec(
        "outer_json_invalid_no_artifacts",
        "launcher",
        "human_gate",
        "Launcher outer JSON was invalid",
        "The launcher output could not be parsed as the expected outer JSON and no valid artifacts were available.",
        ("stdout_or_outer_json", "returncode", "launch_dir"),
    ),
    FailureKindSpec(
        "outer_artifacts_missing",
        "artifact_contract",
        "human_gate",
        "Launcher JSON omitted artifacts",
        "The launcher output was parseable but did not contain the required artifact object.",
        ("stdout_or_outer_json", "artifact_contract_errors"),
    ),
    FailureKindSpec(
        "writer_tool_denied_no_artifacts",
        "writer_runtime",
        "human_gate",
        "Writer tool denied before artifacts",
        "The writer hit a runtime tool denial and exited without valid artifacts.",
        ("transcript_diagnostics", "launch_dir"),
    ),
    FailureKindSpec(
        "canonical_path_leaked_in_tool_result",
        "permission",
        "human_gate",
        "Canonical source path leaked to writer",
        (
            "A prompt or tool result exposed a path under the sensitive source checkout. "
            "Do not retry the same workspace mode; rerun from the safe-worktree launcher path."
        ),
        ("transcript_diagnostics", "command_metadata", "sensitive_path_excerpt"),
    ),
    FailureKindSpec(
        "writer_silent_with_turns",
        "writer_runtime",
        "human_gate",
        "Writer spent turns without artifacts",
        "The writer spent turns or cost but did not produce a useful terminal result or valid artifacts.",
        ("stdout_metrics", "transcript_diagnostics", "launch_dir"),
    ),
    FailureKindSpec(
        "launcher_workspace_error",
        "environment",
        "human_gate",
        "Launcher workspace preparation failed",
        "Safe workspace or prompt preparation failed before the launcher could run.",
        ("execution_workspace_error", "launch_dir"),
    ),
    FailureKindSpec(
        "launcher_prompt_sensitive_path",
        "permission",
        "human_gate",
        "Launcher prompt contained a sensitive path",
        "Prompt safety checks found a sensitive path spelling before launcher execution.",
        ("prompt_safety_check", "launch_dir"),
    ),
    FailureKindSpec(
        "claude_cli_missing",
        "environment",
        "human_gate",
        "Claude CLI is unavailable",
        "The claude CLI was unavailable for an attempt that required the claude-print launcher.",
        ("command_metadata", "launch_dir"),
    ),
    FailureKindSpec(
        "launcher_ineligible",
        "environment",
        "human_gate",
        "Launcher is ineligible",
        "Launcher doctor reported that this launcher cannot run in the current environment.",
        ("launcher_doctor_report",),
    ),
    FailureKindSpec(
        "permission_contract_failure",
        "permission",
        "human_gate",
        "Permission contract failed",
        "The launcher or writer permission contract failed and needs operator attention.",
        ("permission_contract_details",),
    ),
    FailureKindSpec(
        "structured_retryable_failed",
        "child_result",
        "child_controlled",
        "Child result requested retry",
        "The child wrote valid result and handoff artifacts and marked the failure retryable.",
        ("child_result", "valid_result_artifact", "valid_handoff_artifact"),
    ),
    FailureKindSpec(
        "operator_cancelled",
        "operator",
        "terminal",
        "Operator cancelled the phase",
        "An operator cancelled the phase session attempt.",
        ("operator_action",),
    ),
    FailureKindSpec(
        "operator_requested_retry",
        "operator",
        "retry",
        "Operator requested retry",
        "An operator recorded a recovery decision to retry the phase.",
        ("operator_decision",),
    ),
)

_ARTIFACT_ERROR_SPECS = tuple(
    FailureKindSpec(
        kind,
        "artifact_contract",
        "human_gate",
        "Artifact contract error",
        f"The phase artifact contract reported {kind}.",
        ("artifact_contract_errors",),
    )
    for kind in (
        "status_mismatch",
        "result_identity_mismatch",
        "prepared_plan_sha_mismatch",
        "phase_content_sha_mismatch",
        "handoff_identity_mismatch",
        "attempt_mismatch",
        "handoff_status_mismatch",
        "completed_work_units_not_prepared",
        "path_escape",
    )
)

_ALL_SPECS = _SPECS + _ARTIFACT_ERROR_SPECS


def _build_registry(specs: tuple[FailureKindSpec, ...]) -> tuple[dict[str, FailureKindSpec], dict[str, FailureKindSpec]]:
    canonical: dict[str, FailureKindSpec] = {}
    aliases: dict[str, FailureKindSpec] = {}
    for spec in specs:
        if spec.category not in CATEGORIES:
            raise ValueError(f"unknown failure category for {spec.kind}: {spec.category}")
        if spec.retry_class not in RETRY_CLASSES:
            raise ValueError(f"unknown failure retry class for {spec.kind}: {spec.retry_class}")
        if spec.kind in canonical:
            raise ValueError(f"duplicate failure kind: {spec.kind}")
        if spec.kind in aliases:
            raise ValueError(f"failure kind collides with alias: {spec.kind}")
        canonical[spec.kind] = spec
        for alias in spec.aliases:
            if alias in canonical:
                raise ValueError(f"failure alias collides with canonical kind: {alias}")
            if alias in aliases:
                raise ValueError(f"duplicate failure alias: {alias}")
            aliases[alias] = spec
    return canonical, aliases


_BY_KIND, _BY_ALIAS = _build_registry(_ALL_SPECS)


def failure_kind_spec(kind: str | None) -> FailureKindSpec:
    if isinstance(kind, str) and kind:
        if kind in _BY_KIND:
            return _BY_KIND[kind]
        if kind in _BY_ALIAS:
            return _BY_ALIAS[kind]
    return _UNKNOWN_CHILD_RESULT


def failure_kind_details(kind: str | None, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(kind, str) or not kind:
        return {
            "failure_kind": kind,
            "failure_category": None,
            "failure_retry_class": None,
            "failure_operator_title": None,
            "failure_operator_message": None,
            "failure_known": False,
        }
    spec = failure_kind_spec(kind)
    known = kind in _BY_KIND or kind in _BY_ALIAS
    return {
        "failure_kind": kind,
        "failure_category": spec.category,
        "failure_retry_class": spec.retry_class,
        "failure_operator_title": spec.operator_title,
        "failure_operator_message": spec.operator_message,
        "failure_known": known,
    }


def known_failure_kinds() -> tuple[str, ...]:
    return tuple(sorted(spec.kind for spec in _BY_KIND.values() if not spec.deprecated))


def taxonomy_markdown() -> str:
    lines = [
        "# Failure Taxonomy",
        "",
        "Known SwarmDaddy-owned phase-session failure kinds.",
        "",
        "| Kind | Category | Retry class | Operator title | Required evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for kind in known_failure_kinds():
        spec = _BY_KIND[kind]
        required = ", ".join(spec.required_evidence) or "-"
        lines.append(f"| `{spec.kind}` | `{spec.category}` | `{spec.retry_class}` | {spec.operator_title} | `{required}` |")
    lines.extend(
        [
            "",
            "Unknown child-reported values are preserved as raw `failure_kind` values and projected as",
            "`failure_category=child_result` with `failure_retry_class=child_controlled`.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "FailureKindSpec",
    "failure_kind_details",
    "failure_kind_spec",
    "known_failure_kinds",
    "taxonomy_markdown",
]
