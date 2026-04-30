from __future__ import annotations

import unittest

from swarm_do.pipeline.phase_autopilot_policy import (
    AutopilotPolicyInput,
    evaluate_autopilot_policy,
    expand_profile,
    retry_policy_config,
)


class PhaseAutopilotPolicyTests(unittest.TestCase):
    def test_human_gate_launcher_failure_uses_literal_decision(self) -> None:
        decision = evaluate_autopilot_policy(
            _policy_input("claude_cli_missing", retry_class="human_gate"),
            _config(),
        )

        self.assertEqual(decision.action, "human_gate")
        self.assertEqual(decision.policy_reason, "taxonomy_human_gate")
        self.assertEqual(decision.blocked_reason, "retry_policy_human_gate")
        self.assertEqual(decision.retry_policy_decision, "claude_cli_missing")

    def test_deterministic_artifact_error_blocks(self) -> None:
        decision = evaluate_autopilot_policy(
            _policy_input("partial_artifacts_invalid", retry_class="recovery_retry", artifact_error_kinds=("path_escape",)),
            _config(),
        )

        self.assertEqual(decision.action, "human_gate")
        self.assertEqual(decision.policy_reason, "deterministic_contract_failure")
        self.assertEqual(decision.blocked_reason, "deterministic_contract_failure")

    def test_same_failure_limit_blocks_before_retry_budget(self) -> None:
        decision = evaluate_autopilot_policy(
            _policy_input("launcher_nonzero_no_artifacts", same_failure_count=2, attempt=2),
            _config(max_session_attempts=2),
        )

        self.assertEqual(decision.action, "human_gate")
        self.assertEqual(decision.policy_reason, "same_failure_limit")
        self.assertEqual(decision.retry_policy_decision, "same_failure_limit")

    def test_failed_spend_thresholds_use_known_provider_cost_only(self) -> None:
        decision = evaluate_autopilot_policy(
            _policy_input("launcher_nonzero_no_artifacts", current_attempt_cost_usd=1.51, failed_run_cost_usd=1.51),
            _config(max_failed_attempt_cost_usd=1.50),
        )
        self.assertEqual(decision.policy_reason, "failed_attempt_spend_threshold")

        unknown = evaluate_autopilot_policy(
            _policy_input(
                "launcher_nonzero_no_artifacts",
                current_attempt_cost_usd=None,
                cost_confidence="unknown",
                failed_run_cost_usd=0.0,
                unknown_failed_attempt_count=1,
            ),
            _config(max_failed_attempt_cost_usd=0.01),
        )
        self.assertEqual(unknown.policy_reason, "normal_retry")

    def test_child_controlled_unknown_failure_can_retry(self) -> None:
        decision = evaluate_autopilot_policy(
            _policy_input("child_specific_retry", category="child_result", retry_class="child_controlled"),
            _config(),
        )

        self.assertEqual(decision.action, "retry_after_backoff")
        self.assertEqual(decision.policy_reason, "normal_retry")

    def test_retry_after_is_clamped(self) -> None:
        decision = evaluate_autopilot_policy(
            _policy_input("structured_retryable_failed", retry_after_seconds_requested=9999),
            _config(max_retry_after_seconds=1800),
        )

        self.assertEqual(decision.action, "retry_after_backoff")
        self.assertEqual(decision.policy_reason, "retry_after_requested")
        self.assertEqual(decision.retry_after_seconds, 1800)

    def test_dogfood_profile_defaults(self) -> None:
        values = {"max_session_attempts": 2, "max_recovery_attempts": 1, **expand_profile("dogfood")}
        config = retry_policy_config(
            {
                "recovery_timeout_threshold_seconds": 600,
                "retry_sleep_threshold_seconds": 0,
                "short_retry_backoff_seconds": 60,
                "max_retry_after_seconds": 1800,
                "max_consecutive_same_failure_kind": 2,
                **values,
            }
        )

        self.assertEqual(config.autopilot_profile, "dogfood")
        self.assertEqual(config.max_failed_run_cost_usd, 2.0)
        self.assertEqual(config.max_failed_attempt_cost_usd, 1.5)
        self.assertEqual(config.max_phase_attempt_budget_usd, 1.5)


def _config(**overrides):
    policy = {
        "autopilot_profile": "standard",
        "max_session_attempts": 2,
        "max_recovery_attempts": 1,
        "recovery_timeout_threshold_seconds": 600,
        "retry_sleep_threshold_seconds": 0,
        "short_retry_backoff_seconds": 60,
        "max_retry_after_seconds": 1800,
        "max_consecutive_same_failure_kind": 2,
        "max_failed_attempt_cost_usd": None,
        "max_failed_run_cost_usd": None,
        "max_phase_attempt_budget_usd": None,
    }
    policy.update(overrides)
    return retry_policy_config(policy)


def _policy_input(
    failure_kind: str,
    *,
    category: str = "launcher",
    retry_class: str = "retry",
    attempt: int = 1,
    same_failure_count: int = 1,
    retry_after_seconds_requested: int | None = None,
    current_attempt_cost_usd: float | None = 0.01,
    cost_confidence: str | None = "provider_reported",
    failed_run_cost_usd: float = 0.01,
    unknown_failed_attempt_count: int = 0,
    artifact_error_kinds: tuple[str, ...] = (),
) -> AutopilotPolicyInput:
    return AutopilotPolicyInput(
        failure_kind=failure_kind,
        failure_category=category,
        failure_retry_class=retry_class,
        attempt=attempt,
        same_failure_count=same_failure_count,
        max_session_attempts=2,
        recovery_attempts_used=0,
        needs_recovery_retry=False,
        returncode=1,
        artifact_error_kinds=artifact_error_kinds,
        partial_artifacts=False,
        changed_file_count=0,
        elapsed_seconds=1.0,
        retry_after_seconds_requested=retry_after_seconds_requested,
        current_attempt_cost_usd=current_attempt_cost_usd,
        cost_confidence=cost_confidence,
        failed_phase_cost_usd=failed_run_cost_usd,
        failed_run_cost_usd=failed_run_cost_usd,
        unknown_failed_attempt_count=unknown_failed_attempt_count,
        handoff_do_not_retry=False,
    )


if __name__ == "__main__":
    unittest.main()
