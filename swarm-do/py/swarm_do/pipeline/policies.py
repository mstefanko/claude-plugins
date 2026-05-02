"""Shared policy facade for retry and provider policy display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .phase_autopilot_policy import (
    DEFAULT_RETRY_POLICY_DICT,
    POLICY_ACTIONS,
    POLICY_PROFILES,
    POLICY_REASONS,
    AutopilotPolicyConfig,
    AutopilotPolicyDecision,
    AutopilotPolicyInput,
    ResolvedPolicyUpdate,
    default_retry_policy,
    evaluate_autopilot_policy,
    expand_profile,
    fallback_retry_after_seconds,
    profile_defaults,
    retry_policy_config,
    validate_policy_overrides,
)
from .provider_review import ReviewProviderPolicy


@dataclass(frozen=True)
class ResolvedPolicySummary:
    autopilot_profile: str
    retry: dict[str, Any]
    budget: dict[str, Any]
    review_providers: dict[str, Any] | None


def resolved_policy_summary(
    retry_policy: Mapping[str, Any] | AutopilotPolicyConfig | None = None,
    *,
    review_providers: Mapping[str, Any] | ReviewProviderPolicy | None = None,
) -> ResolvedPolicySummary:
    config = retry_policy if isinstance(retry_policy, AutopilotPolicyConfig) else retry_policy_config(retry_policy or default_retry_policy())
    return ResolvedPolicySummary(
        autopilot_profile=config.autopilot_profile,
        retry={
            "max_session_attempts": config.max_session_attempts,
            "max_recovery_attempts": config.max_recovery_attempts,
            "recovery_timeout_threshold_seconds": config.recovery_timeout_threshold_seconds,
            "retry_sleep_threshold_seconds": config.retry_sleep_threshold_seconds,
            "short_retry_backoff_seconds": config.short_retry_backoff_seconds,
            "max_retry_after_seconds": config.max_retry_after_seconds,
            "max_consecutive_same_failure_kind": config.max_consecutive_same_failure_kind,
        },
        budget={
            "max_failed_attempt_cost_usd": config.max_failed_attempt_cost_usd,
            "max_failed_run_cost_usd": config.max_failed_run_cost_usd,
            "max_phase_attempt_budget_usd": config.max_phase_attempt_budget_usd,
        },
        review_providers=_review_provider_dict(review_providers),
    )


def _review_provider_dict(value: Mapping[str, Any] | ReviewProviderPolicy | None) -> dict[str, Any] | None:
    if isinstance(value, ReviewProviderPolicy):
        return value.as_dict()
    if isinstance(value, Mapping):
        return dict(value)
    return None


__all__ = [
    "AutopilotPolicyConfig",
    "AutopilotPolicyDecision",
    "AutopilotPolicyInput",
    "DEFAULT_RETRY_POLICY_DICT",
    "POLICY_ACTIONS",
    "POLICY_PROFILES",
    "POLICY_REASONS",
    "ResolvedPolicySummary",
    "ResolvedPolicyUpdate",
    "ReviewProviderPolicy",
    "default_retry_policy",
    "evaluate_autopilot_policy",
    "expand_profile",
    "fallback_retry_after_seconds",
    "profile_defaults",
    "resolved_policy_summary",
    "retry_policy_config",
    "validate_policy_overrides",
]
