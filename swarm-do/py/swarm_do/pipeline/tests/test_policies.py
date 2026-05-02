from __future__ import annotations

import dataclasses
import json
import unittest

from swarm_do.pipeline import phase_autopilot_policy, phase_pump, phase_sessions, policies


HISTORICAL_DEFAULT_RETRY_POLICY = {
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


class PoliciesTests(unittest.TestCase):
    def test_reexported_autopilot_symbols_preserve_identity(self) -> None:
        for name in phase_autopilot_policy.__all__:
            self.assertIs(getattr(policies, name), getattr(phase_autopilot_policy, name), name)

    def test_resolved_policy_update_identity_survives_consumers(self) -> None:
        update = policies.ResolvedPolicyUpdate(
            forced_overrides={"max_session_attempts": 1},
            default_overrides={"max_phase_attempt_budget_usd": 1.25},
        )
        state = {
            "schema_version": 1,
            "run_id": "01J00000000000000000000000",
            "prepared_artifact_path": "prepared_plan.v1.json",
            "prepared_plan_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "created_at": "2026-05-02T00:00:00Z",
            "updated_at": "2026-05-02T00:00:00Z",
            "mode": "cli-pump",
            "lease_policy": {
                "claim_ttl_seconds": 900,
                "running_ttl_seconds": 14400,
                "refresh_interval_seconds": 300,
            },
            "phases": [],
        }

        configured = phase_sessions._configure_retry_policy_in_state(state, update)

        self.assertTrue(phase_pump._policy_update_has_values(update))
        self.assertEqual(configured["retry_policy"]["max_session_attempts"], 1)
        self.assertEqual(configured["retry_policy"]["max_phase_attempt_budget_usd"], 1.25)

    def test_resolved_policy_summary_json_round_trips(self) -> None:
        config = policies.retry_policy_config(
            {
                **policies.default_retry_policy(),
                "max_failed_attempt_cost_usd": 1.5,
                "max_phase_attempt_budget_usd": 2.5,
            }
        )
        review = policies.ReviewProviderPolicy(selection="codex", min_success=2, max_parallel=3)

        summary = policies.resolved_policy_summary(config, review_providers=review)
        payload = dataclasses.asdict(summary)

        self.assertEqual(json.loads(json.dumps(payload, sort_keys=True)), payload)
        self.assertEqual(payload["autopilot_profile"], "standard")
        self.assertEqual(payload["budget"]["max_phase_attempt_budget_usd"], 2.5)
        self.assertEqual(payload["review_providers"]["selection"], "codex")

    def test_validate_policy_overrides_names_invalid_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, r"policy\[max_session_attempts\] expected integer, got 'two'"):
            policies.validate_policy_overrides({"max_session_attempts": "two"})
        with self.assertRaisesRegex(ValueError, r"policy\[max_failed_attempt_cost_usd\] expected numeric threshold, got 'many'"):
            policies.validate_policy_overrides({"max_failed_attempt_cost_usd": "many"})

    def test_default_retry_policy_matches_historical_literal(self) -> None:
        self.assertEqual(policies.default_retry_policy(), HISTORICAL_DEFAULT_RETRY_POLICY)
        self.assertEqual(policies.retry_policy_config({}), policies.retry_policy_config(HISTORICAL_DEFAULT_RETRY_POLICY))
        self.assertEqual(policies.normalize_retry_policy({}), HISTORICAL_DEFAULT_RETRY_POLICY)


if __name__ == "__main__":
    unittest.main()
