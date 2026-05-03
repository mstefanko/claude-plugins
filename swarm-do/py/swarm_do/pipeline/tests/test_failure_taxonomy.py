from __future__ import annotations

import unittest

from swarm_do.pipeline.failure_taxonomy import failure_kind_details, known_failure_kinds, taxonomy_markdown


class FailureTaxonomyTests(unittest.TestCase):
    def test_known_failure_kind_returns_operational_details(self) -> None:
        details = failure_kind_details("launcher_nonzero_no_artifacts")

        self.assertEqual(details["failure_category"], "launcher")
        self.assertEqual(details["failure_retry_class"], "retry")
        self.assertEqual(details["failure_operator_title"], "Launcher exited before artifacts")
        self.assertTrue(details["failure_known"])

    def test_canonical_path_leak_kind_is_permission_human_gate(self) -> None:
        details = failure_kind_details("canonical_path_leaked_in_tool_result")

        self.assertEqual(details["failure_category"], "permission")
        self.assertEqual(details["failure_retry_class"], "human_gate")
        self.assertEqual(details["failure_operator_title"], "Canonical source path leaked to writer")
        self.assertTrue(details["failure_known"])

    def test_unknown_child_reported_failure_is_child_controlled(self) -> None:
        details = failure_kind_details("worker_custom_failure")

        self.assertEqual(details["failure_kind"], "worker_custom_failure")
        self.assertEqual(details["failure_category"], "child_result")
        self.assertEqual(details["failure_retry_class"], "child_controlled")
        self.assertFalse(details["failure_known"])

    def test_taxonomy_markdown_includes_all_known_values(self) -> None:
        markdown = taxonomy_markdown()

        for kind in known_failure_kinds():
            self.assertIn(f"`{kind}`", markdown)

    def test_phase_artifact_contract_error_kinds_are_known(self) -> None:
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
        ):
            with self.subTest(kind=kind):
                self.assertIn(kind, known_failure_kinds())
                self.assertTrue(failure_kind_details(kind)["failure_known"])

    def test_mco_and_dispatcher_fanout_kinds_are_known(self) -> None:
        expected = {
            "RETRYABLE_TIMEOUT": "retry",
            "RETRYABLE_RATE_LIMIT": "retry",
            "RETRYABLE_TRANSIENT_NETWORK": "retry",
            "NON_RETRYABLE_AUTH": "human_gate",
            "NON_RETRYABLE_INVALID_INPUT": "human_gate",
            "NON_RETRYABLE_UNSUPPORTED_CAPABILITY": "human_gate",
            "NORMALIZATION_ERROR": "human_gate",
            "PARTIAL_SUCCESS": "terminal",
            "dispatcher_missing_agent_tool": "human_gate",
            "dispatcher_token_exhausted": "retry",
            "stage_result_missing": "human_gate",
            "sub_agent_error": "retry",
        }
        for kind, retry_class in expected.items():
            with self.subTest(kind=kind):
                self.assertIn(kind, known_failure_kinds())
                self.assertEqual(failure_kind_details(kind)["failure_retry_class"], retry_class)


if __name__ == "__main__":
    unittest.main()
