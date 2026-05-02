"""Pure durable-run autopilot retry policy evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


POLICY_PROFILES = ("standard", "dogfood", "strict")
POLICY_ACTIONS = (
    "retry",
    "retry_after_backoff",
    "recovery_retry",
    "human_gate",
    "retry_exhausted",
    "terminal",
)
POLICY_REASONS = (
    "taxonomy_human_gate",
    "deterministic_contract_failure",
    "permission_contract_failure",
    "same_failure_limit",
    "retry_budget_exhausted",
    "recovery_retry_budget_exhausted",
    "failed_attempt_spend_threshold",
    "failed_run_spend_threshold",
    "child_do_not_retry",
    "child_nonretryable_failed",
    "retry_after_requested",
    "normal_retry",
    "recovery_retry_required",
)

DEFAULT_BACKOFF_SCHEDULE_SECONDS = (60, 180, 600)

DEFAULT_RETRY_POLICY_DICT = {
    "max_session_attempts": 2,
    "max_recovery_attempts": 1,
    "recovery_timeout_threshold_seconds": 600,
    "retry_sleep_threshold_seconds": 0,
    "short_retry_backoff_seconds": 60,
    "max_retry_after_seconds": 1800,
    "max_consecutive_same_failure_kind": 2,
    "autopilot_profile": "standard",
    "max_failed_attempt_cost_usd": None,
    "max_failed_run_cost_usd": None,
    "max_phase_attempt_budget_usd": None,
    "worktree_baseline_path": None,
    "worktree_baseline_warning": None,
}

_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "standard": {},
    "dogfood": {
        "max_failed_run_cost_usd": 2.00,
        "max_failed_attempt_cost_usd": 1.50,
        "max_phase_attempt_budget_usd": 1.50,
    },
    "strict": {
        "max_session_attempts": 1,
        "max_recovery_attempts": 0,
        "max_phase_attempt_budget_usd": 1.00,
    },
}

_DETERMINISTIC_ARTIFACT_ERROR_KINDS = {
    "path_escape",
    "result_identity_mismatch",
    "prepared_plan_sha_mismatch",
    "phase_content_sha_mismatch",
    "handoff_identity_mismatch",
    "attempt_mismatch",
    "handoff_status_mismatch",
    "completed_work_units_not_prepared",
}


@dataclass(frozen=True)
class AutopilotPolicyConfig:
    autopilot_profile: str
    max_session_attempts: int
    max_recovery_attempts: int
    recovery_timeout_threshold_seconds: int
    retry_sleep_threshold_seconds: int
    short_retry_backoff_seconds: int
    max_retry_after_seconds: int
    max_consecutive_same_failure_kind: int
    max_failed_attempt_cost_usd: float | None
    max_failed_run_cost_usd: float | None
    max_phase_attempt_budget_usd: float | None


@dataclass(frozen=True)
class AutopilotPolicyInput:
    failure_kind: str
    failure_category: str | None
    failure_retry_class: str | None
    attempt: int
    same_failure_count: int
    max_session_attempts: int
    recovery_attempts_used: int
    needs_recovery_retry: bool
    returncode: int | None
    artifact_error_kinds: tuple[str, ...]
    partial_artifacts: bool
    changed_file_count: int
    elapsed_seconds: float | None
    retry_after_seconds_requested: int | None
    current_attempt_cost_usd: float | None
    cost_confidence: str | None
    failed_phase_cost_usd: float
    failed_run_cost_usd: float
    unknown_failed_attempt_count: int
    handoff_do_not_retry: bool


@dataclass(frozen=True)
class AutopilotPolicyDecision:
    action: str
    policy_reason: str
    blocked_reason: str | None
    retry_policy_decision: str
    retry_after_seconds: int | None
    operator_title: str | None
    operator_message: str | None
    inputs: dict[str, Any]


@dataclass(frozen=True)
class ResolvedPolicyUpdate:
    forced_overrides: dict[str, Any]
    default_overrides: dict[str, Any]


def profile_defaults(profile: str) -> dict[str, Any]:
    if profile not in POLICY_PROFILES:
        raise ValueError(f"unsupported autopilot policy profile: {profile}")
    return dict(_PROFILE_DEFAULTS[profile])


def expand_profile(profile: str) -> dict[str, Any]:
    expanded = profile_defaults(profile)
    expanded["autopilot_profile"] = profile
    return expanded


def default_retry_policy() -> dict[str, Any]:
    return dict(DEFAULT_RETRY_POLICY_DICT)


def retry_policy_config(policy: Mapping[str, Any]) -> AutopilotPolicyConfig:
    profile = str(policy.get("autopilot_profile") or "standard")
    if profile not in POLICY_PROFILES:
        raise ValueError(f"unsupported autopilot policy profile: {profile}")
    defaults = DEFAULT_RETRY_POLICY_DICT
    return AutopilotPolicyConfig(
        autopilot_profile=profile,
        max_session_attempts=_positive_int(policy.get("max_session_attempts"), default=int(defaults["max_session_attempts"]), minimum=1),
        max_recovery_attempts=_positive_int(policy.get("max_recovery_attempts"), default=int(defaults["max_recovery_attempts"]), minimum=0),
        recovery_timeout_threshold_seconds=_positive_int(
            policy.get("recovery_timeout_threshold_seconds"),
            default=int(defaults["recovery_timeout_threshold_seconds"]),
            minimum=1,
        ),
        retry_sleep_threshold_seconds=_positive_int(
            policy.get("retry_sleep_threshold_seconds"),
            default=int(defaults["retry_sleep_threshold_seconds"]),
            minimum=0,
        ),
        short_retry_backoff_seconds=_positive_int(
            policy.get("short_retry_backoff_seconds"),
            default=int(defaults["short_retry_backoff_seconds"]),
            minimum=0,
        ),
        max_retry_after_seconds=_positive_int(
            policy.get("max_retry_after_seconds"),
            default=int(defaults["max_retry_after_seconds"]),
            minimum=0,
        ),
        max_consecutive_same_failure_kind=_positive_int(
            policy.get("max_consecutive_same_failure_kind"),
            default=int(defaults["max_consecutive_same_failure_kind"]),
            minimum=1,
        ),
        max_failed_attempt_cost_usd=_optional_nonnegative_float(policy.get("max_failed_attempt_cost_usd")),
        max_failed_run_cost_usd=_optional_nonnegative_float(policy.get("max_failed_run_cost_usd")),
        max_phase_attempt_budget_usd=_optional_nonnegative_float(policy.get("max_phase_attempt_budget_usd")),
    )


def evaluate_autopilot_policy(
    policy_input: AutopilotPolicyInput,
    config: AutopilotPolicyConfig,
    *,
    operator_title: str | None = None,
    operator_message: str | None = None,
) -> AutopilotPolicyDecision:
    inputs = _policy_inputs(policy_input, config)
    failure_kind = policy_input.failure_kind
    retry_class = policy_input.failure_retry_class

    if retry_class == "human_gate" and failure_kind in {"claude_cli_missing", "launcher_ineligible"}:
        return _decision(
            "human_gate",
            "taxonomy_human_gate",
            blocked_reason="retry_policy_human_gate",
            retry_policy_decision=failure_kind,
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if retry_class == "human_gate" and failure_kind in {"launcher_workspace_error", "launcher_prompt_sensitive_path"}:
        return _decision(
            "human_gate",
            "deterministic_contract_failure",
            blocked_reason="retry_policy_human_gate",
            retry_policy_decision="deterministic_contract_failure",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if retry_class == "human_gate" and failure_kind in {"canonical_path_leaked_in_tool_result", "permission_contract_failure"}:
        return _decision(
            "human_gate",
            "permission_contract_failure",
            blocked_reason="permission_contract_failure",
            retry_policy_decision="permission_contract_failure",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if failure_kind in {"outer_json_invalid_no_artifacts", "outer_artifacts_missing"} and policy_input.returncode == 0:
        return _deterministic_human_gate(inputs, operator_title=operator_title, operator_message=operator_message)

    if failure_kind in {"writer_tool_denied_no_artifacts", "writer_silent_with_turns"} and policy_input.returncode == 0:
        return _deterministic_human_gate(inputs, operator_title=operator_title, operator_message=operator_message)

    if set(policy_input.artifact_error_kinds) & _DETERMINISTIC_ARTIFACT_ERROR_KINDS:
        return _decision(
            "human_gate",
            "deterministic_contract_failure",
            blocked_reason="deterministic_contract_failure",
            retry_policy_decision="deterministic_contract_failure",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if policy_input.same_failure_count >= config.max_consecutive_same_failure_kind:
        return _decision(
            "human_gate",
            "same_failure_limit",
            blocked_reason="retry_policy_human_gate",
            retry_policy_decision="same_failure_limit",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if (
        config.max_failed_attempt_cost_usd is not None
        and policy_input.cost_confidence == "provider_reported"
        and policy_input.current_attempt_cost_usd is not None
        and policy_input.current_attempt_cost_usd > config.max_failed_attempt_cost_usd
    ):
        return _decision(
            "human_gate",
            "failed_attempt_spend_threshold",
            blocked_reason="retry_policy_human_gate",
            retry_policy_decision="spend_threshold",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if config.max_failed_run_cost_usd is not None and policy_input.failed_run_cost_usd > config.max_failed_run_cost_usd:
        return _decision(
            "human_gate",
            "failed_run_spend_threshold",
            blocked_reason="retry_policy_human_gate",
            retry_policy_decision="spend_threshold",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if policy_input.handoff_do_not_retry:
        return _decision(
            "human_gate",
            "child_do_not_retry",
            blocked_reason="child_reported_blocked",
            retry_policy_decision="child_do_not_retry",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if retry_class == "terminal":
        return _decision(
            "terminal",
            "child_nonretryable_failed",
            blocked_reason=None,
            retry_policy_decision="child_nonretryable_failed",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if policy_input.needs_recovery_retry and policy_input.recovery_attempts_used >= config.max_recovery_attempts:
        return _decision(
            "retry_exhausted",
            "recovery_retry_budget_exhausted",
            blocked_reason=None,
            retry_policy_decision="retry_exhausted",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if policy_input.attempt >= policy_input.max_session_attempts:
        return _decision(
            "retry_exhausted",
            "retry_budget_exhausted",
            blocked_reason=None,
            retry_policy_decision="retry_exhausted",
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if policy_input.needs_recovery_retry:
        delay = fallback_retry_after_seconds(policy_input.attempt, config)
        return _decision(
            "recovery_retry",
            "recovery_retry_required",
            blocked_reason=None,
            retry_policy_decision="recovery_retry",
            retry_after_seconds=delay if delay > 0 else None,
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    if policy_input.retry_after_seconds_requested is not None:
        delay = min(max(0, int(policy_input.retry_after_seconds_requested)), config.max_retry_after_seconds)
        return _decision(
            "retry_after_backoff" if delay > 0 else "retry",
            "retry_after_requested",
            blocked_reason=None,
            retry_policy_decision="retry",
            retry_after_seconds=delay if delay > 0 else None,
            inputs=inputs,
            operator_title=operator_title,
            operator_message=operator_message,
        )

    delay = fallback_retry_after_seconds(policy_input.attempt, config)
    return _decision(
        "retry_after_backoff" if delay > 0 else "retry",
        "normal_retry",
        blocked_reason=None,
        retry_policy_decision="retry",
        retry_after_seconds=delay if delay > 0 else None,
        inputs=inputs,
        operator_title=operator_title,
        operator_message=operator_message,
    )


def fallback_retry_after_seconds(attempt: int, config: AutopilotPolicyConfig) -> int:
    maximum = max(0, int(config.max_retry_after_seconds))
    if config.short_retry_backoff_seconds > 0 and attempt <= 1:
        return min(config.short_retry_backoff_seconds, maximum)
    index = min(max(int(attempt) - 1, 0), len(DEFAULT_BACKOFF_SCHEDULE_SECONDS) - 1)
    return min(DEFAULT_BACKOFF_SCHEDULE_SECONDS[index], maximum)


def validate_policy_overrides(values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        if key == "autopilot_profile":
            if value not in POLICY_PROFILES:
                raise ValueError(f"unsupported autopilot policy profile: {value}")
            continue
        if key in {
            "max_failed_attempt_cost_usd",
            "max_failed_run_cost_usd",
            "max_phase_attempt_budget_usd",
        }:
            _optional_nonnegative_float(value, key=key)
            continue
        if key in {
            "max_session_attempts",
            "max_recovery_attempts",
            "recovery_timeout_threshold_seconds",
            "retry_sleep_threshold_seconds",
            "short_retry_backoff_seconds",
            "max_retry_after_seconds",
            "max_consecutive_same_failure_kind",
        }:
            minimum = 1 if key in {"max_session_attempts", "recovery_timeout_threshold_seconds", "max_consecutive_same_failure_kind"} else 0
            _positive_int(value, default=minimum, minimum=minimum, key=key)


def _policy_inputs(policy_input: AutopilotPolicyInput, config: AutopilotPolicyConfig) -> dict[str, Any]:
    values = asdict(policy_input)
    values["artifact_error_kinds"] = list(policy_input.artifact_error_kinds)
    values.update(
        {
            "max_recovery_attempts": config.max_recovery_attempts,
            "max_consecutive_same_failure_kind": config.max_consecutive_same_failure_kind,
            "recovery_timeout_threshold_seconds": config.recovery_timeout_threshold_seconds,
            "retry_sleep_threshold_seconds": config.retry_sleep_threshold_seconds,
            "short_retry_backoff_seconds": config.short_retry_backoff_seconds,
            "max_retry_after_seconds": config.max_retry_after_seconds,
            "max_failed_attempt_cost_usd": config.max_failed_attempt_cost_usd,
            "max_failed_run_cost_usd": config.max_failed_run_cost_usd,
            "max_phase_attempt_budget_usd": config.max_phase_attempt_budget_usd,
        }
    )
    return values


def _deterministic_human_gate(
    inputs: dict[str, Any],
    *,
    operator_title: str | None,
    operator_message: str | None,
) -> AutopilotPolicyDecision:
    return _decision(
        "human_gate",
        "deterministic_contract_failure",
        blocked_reason="retry_policy_human_gate",
        retry_policy_decision="deterministic_contract_failure",
        inputs=inputs,
        operator_title=operator_title,
        operator_message=operator_message,
    )


def _decision(
    action: str,
    policy_reason: str,
    *,
    blocked_reason: str | None,
    retry_policy_decision: str,
    inputs: dict[str, Any],
    operator_title: str | None,
    operator_message: str | None,
    retry_after_seconds: int | None = None,
) -> AutopilotPolicyDecision:
    if action not in POLICY_ACTIONS:
        raise ValueError(f"unsupported policy action: {action}")
    if policy_reason not in POLICY_REASONS:
        raise ValueError(f"unsupported policy reason: {policy_reason}")
    return AutopilotPolicyDecision(
        action=action,
        policy_reason=policy_reason,
        blocked_reason=blocked_reason,
        retry_policy_decision=retry_policy_decision,
        retry_after_seconds=retry_after_seconds,
        operator_title=operator_title,
        operator_message=operator_message,
        inputs=inputs,
    )


def _positive_int(value: Any, *, default: int, minimum: int, key: str | None = None) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        prefix = f"policy[{key}] " if key else ""
        raise ValueError(f"{prefix}expected integer, got {value!r}")
    if value < minimum:
        prefix = f"policy[{key}] " if key else "policy "
        raise ValueError(f"{prefix}integer value {value!r} is less than minimum {minimum}")
    return value


def _optional_nonnegative_float(value: Any, *, key: str | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        prefix = f"policy[{key}] " if key else ""
        raise ValueError(f"{prefix}expected numeric threshold, got {value!r}")
    if float(value) < 0:
        prefix = f"policy[{key}] " if key else "policy "
        raise ValueError(f"{prefix}threshold {value!r} is less than minimum 0")
    return float(value)


__all__ = [
    "AutopilotPolicyConfig",
    "AutopilotPolicyDecision",
    "AutopilotPolicyInput",
    "DEFAULT_RETRY_POLICY_DICT",
    "POLICY_ACTIONS",
    "POLICY_PROFILES",
    "POLICY_REASONS",
    "ResolvedPolicyUpdate",
    "default_retry_policy",
    "evaluate_autopilot_policy",
    "expand_profile",
    "fallback_retry_after_seconds",
    "profile_defaults",
    "retry_policy_config",
    "validate_policy_overrides",
]
