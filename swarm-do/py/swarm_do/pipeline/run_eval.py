"""Fixture-backed assertions over read-only run traces."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .run_trace import RunTrace, build_trace_from_run_dir, trace_to_dict
from .simple_yaml import YamlError, load_yaml


EVAL_EXPECTATION_SCHEMA: dict[str, Any] = {
    "schema_version": 1,
    "required_keys": {
        "schema_version",
        "required_artifacts",
        "expected_phase_transitions",
        "expected_attempts",
        "expected_warnings",
        "forbidden_warnings",
        "unrecognized_artifacts_allowed",
    },
}


@dataclass(frozen=True)
class EvalMismatch:
    kind: str
    expected: Any
    actual: Any
    path: str


@dataclass(frozen=True)
class FixtureEvalResult:
    fixture: str
    status: str
    first_mismatch: EvalMismatch | None
    trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class EvalRunResult:
    fixture_dir: str
    status: str
    results: list[FixtureEvalResult]
    first_mismatch: EvalMismatch | None


class FixtureLoadError(ValueError):
    """Raised when a trace fixture is malformed."""


def discover_fixtures(fixture_dir: Path) -> list[Path]:
    root = Path(fixture_dir)
    if (root / "expectation.yaml").is_file():
        return [root]
    return sorted(
        [path for path in root.iterdir() if path.is_dir() and (path / "expectation.yaml").is_file()],
        key=lambda path: path.name,
    )


def run_fixtures(fixture_dir: Path, *, include_trace: bool = False) -> EvalRunResult:
    fixtures = discover_fixtures(fixture_dir)
    if not fixtures:
        raise FixtureLoadError(f"no run-trace fixtures found under {fixture_dir}")
    results = [run_fixture(path, include_trace=include_trace) for path in fixtures]
    first = next((item.first_mismatch for item in results if item.first_mismatch is not None), None)
    return EvalRunResult(
        fixture_dir=str(Path(fixture_dir)),
        status="passed" if first is None else "failed",
        results=results,
        first_mismatch=first,
    )


def run_fixture(fixture_dir: Path, *, include_trace: bool = False) -> FixtureEvalResult:
    fixture = Path(fixture_dir)
    expectation = load_expectation(fixture / "expectation.yaml")
    run_dir = fixture / "run"
    if not run_dir.is_dir():
        raise FileNotFoundError(f"fixture run dir not found: {run_dir}")
    trace = build_trace_from_run_dir(
        run_dir,
        data_dir=fixture,
        events_path=fixture / "events.jsonl",
        active_path=fixture / "active-run.json",
        worktree_manifest_path=fixture / "worktrees" / _expected_run_id(expectation) / "manifest.json",
        load_full_events=bool(expectation.get("load_full_events")),
    )
    mismatch = first_mismatch(trace, expectation)
    return FixtureEvalResult(
        fixture=fixture.name,
        status="passed" if mismatch is None else "failed",
        first_mismatch=mismatch,
        trace=trace_to_dict(trace) if include_trace else None,
    )


def load_expectation(path: Path) -> dict[str, Any]:
    try:
        value = load_yaml(path)
    except (OSError, YamlError) as exc:
        raise FixtureLoadError(f"cannot load expectation {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FixtureLoadError("expectation root must be a mapping")
    _validate_expectation(value)
    return value


def first_mismatch(trace: RunTrace, expectation: Mapping[str, Any]) -> EvalMismatch | None:
    artifacts = {artifact.path for artifact in trace.artifacts}
    for required in expectation.get("required_artifacts") or []:
        if required not in artifacts:
            return EvalMismatch("missing_required_artifact", required, sorted(artifacts), str(required))

    phase_by_id = {phase.phase_id: phase for phase in trace.phases}
    for expected in expectation.get("expected_phase_transitions") or []:
        if not isinstance(expected, Mapping):
            continue
        phase_id = str(expected.get("phase_id") or "")
        statuses = [str(item) for item in expected.get("statuses") or []]
        actual = phase_by_id.get(phase_id)
        actual_statuses = actual.status_transitions if actual is not None else None
        if actual_statuses != statuses:
            return EvalMismatch("phase_transition_mismatch", statuses, actual_statuses, f"phases.{phase_id}.status_transitions")

    attempts = {(attempt.phase_id, attempt.attempt_number): attempt for attempt in trace.attempts}
    for expected in expectation.get("expected_attempts") or []:
        if not isinstance(expected, Mapping):
            continue
        key = (str(expected.get("phase_id") or ""), int(expected.get("attempt_number") or 0))
        actual = attempts.get(key)
        if actual is None:
            return EvalMismatch("missing_attempt", dict(expected), None, f"attempts.{key[0]}.{key[1]}")
        for field in ("failure_kind", "retry_decision"):
            if field in expected and getattr(actual, field) != expected[field]:
                return EvalMismatch("attempt_field_mismatch", expected[field], getattr(actual, field), f"attempts.{key[0]}.{key[1]}.{field}")
        if "stage_controller" in expected and actual.stage_controller != expected["stage_controller"]:
            return EvalMismatch("stage_controller_mismatch", expected["stage_controller"], actual.stage_controller, f"attempts.{key[0]}.{key[1]}.stage_controller")

    provider_count = expectation.get("expected_provider_reviews")
    if isinstance(provider_count, int) and len(trace.provider_reviews) != provider_count:
        return EvalMismatch("provider_review_count_mismatch", provider_count, len(trace.provider_reviews), "provider_reviews")

    worktree_count = expectation.get("expected_worktree_observations")
    if isinstance(worktree_count, int) and len(trace.worktree_observations) != worktree_count:
        return EvalMismatch("worktree_observation_count_mismatch", worktree_count, len(trace.worktree_observations), "worktree_observations")

    actual_warnings = [warning.kind for warning in trace.warnings]
    expected_warnings = [str(item) for item in expectation.get("expected_warnings") or []]
    if expected_warnings:
        for warning in expected_warnings:
            if warning not in actual_warnings:
                return EvalMismatch("missing_expected_warning", warning, actual_warnings, "warnings")
    elif actual_warnings:
        return EvalMismatch("unexpected_warning", [], actual_warnings, "warnings")
    for warning in expectation.get("forbidden_warnings") or []:
        if warning in actual_warnings:
            return EvalMismatch("forbidden_warning", warning, actual_warnings, "warnings")

    if not bool(expectation.get("unrecognized_artifacts_allowed")) and trace.unrecognized_artifacts:
        return EvalMismatch("unrecognized_artifacts", [], trace.unrecognized_artifacts, "unrecognized_artifacts")
    return None


def expectation_from_trace(trace: RunTrace) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": trace.run_id,
        "required_artifacts": _default_required_artifacts(trace),
        "expected_phase_transitions": [
            {"phase_id": phase.phase_id, "statuses": list(phase.status_transitions)}
            for phase in trace.phases
        ],
        "expected_attempts": [
            {
                "phase_id": attempt.phase_id,
                "attempt_number": attempt.attempt_number,
                "failure_kind": attempt.failure_kind,
                "retry_decision": attempt.retry_decision,
            }
            for attempt in trace.attempts
        ],
        "expected_warnings": [warning.kind for warning in trace.warnings],
        "forbidden_warnings": ["malformed_result"],
        "unrecognized_artifacts_allowed": False,
    }


def expectation_to_yaml(expectation: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _append_yaml(lines, dict(expectation), indent=0)
    return "\n".join(lines).rstrip() + "\n"


def result_to_dict(result: EvalRunResult | FixtureEvalResult | EvalMismatch) -> dict[str, Any]:
    return asdict(result)


def result_to_json(result: EvalRunResult | FixtureEvalResult | EvalMismatch) -> str:
    return json.dumps(result_to_dict(result), indent=2, sort_keys=True) + "\n"


def _validate_expectation(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != 1:
        raise FixtureLoadError("expectation schema_version must be 1")
    for key in EVAL_EXPECTATION_SCHEMA["required_keys"]:
        if key not in value:
            raise FixtureLoadError(f"expectation missing required key: {key}")
    _assert_list(value, "required_artifacts")
    _assert_list(value, "expected_phase_transitions")
    _assert_list(value, "expected_attempts")
    _assert_list(value, "expected_warnings")
    _assert_list(value, "forbidden_warnings")
    if not isinstance(value.get("unrecognized_artifacts_allowed"), bool):
        raise FixtureLoadError("unrecognized_artifacts_allowed must be boolean")


def _assert_list(value: Mapping[str, Any], key: str) -> None:
    if not isinstance(value.get(key), list):
        raise FixtureLoadError(f"{key} must be a list")


def _expected_run_id(expectation: Mapping[str, Any]) -> str:
    value = expectation.get("run_id")
    return str(value) if value else "run"


def _default_required_artifacts(trace: RunTrace) -> list[str]:
    required = ["prepared_plan.v1.json", "phase_sessions.v1.json"]
    required.extend(
        _run_relative_artifact_path(attempt.evidence_path)
        for attempt in trace.attempts
        if attempt.evidence_path
    )
    return required


def _run_relative_artifact_path(path: str) -> str:
    parts = Path(path).parts
    if parts and parts[0] == "run":
        return Path(*parts[1:]).as_posix()
    if len(parts) >= 3 and parts[0] == "runs":
        return Path(*parts[2:]).as_posix()
    return path


def _append_yaml(lines: list[str], value: Any, *, indent: int) -> None:
    prefix = " " * indent
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                lines.append(f"{prefix}{key}:")
                _append_yaml(lines, item, indent=indent + 2)
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                lines.append(f"{prefix}-")
                _append_yaml(lines, item, indent=indent + 2)
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                _append_yaml(lines, item, indent=indent + 2)
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
    else:
        lines.append(f"{prefix}{_yaml_scalar(value)}")


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value))


__all__ = [
    "EVAL_EXPECTATION_SCHEMA",
    "EvalMismatch",
    "EvalRunResult",
    "FixtureEvalResult",
    "FixtureLoadError",
    "discover_fixtures",
    "expectation_from_trace",
    "expectation_to_yaml",
    "first_mismatch",
    "load_expectation",
    "result_to_dict",
    "result_to_json",
    "run_fixture",
    "run_fixtures",
]
