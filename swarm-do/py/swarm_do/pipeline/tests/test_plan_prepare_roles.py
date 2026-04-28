from __future__ import annotations

import unittest

from swarm_do.pipeline.permissions import load_fragment
from swarm_do.pipeline.prepare import (
    STATUS_NEEDS_INPUT,
    STATUS_READY,
    run_plan_review_loop,
    validate_plan_review_finding,
)


BLOCKING_FINDING = {
    "severity": "blocking",
    "phase_id": "3",
    "location": "Phase 3 / Acceptance Criteria",
    "reason": "Execution would proceed without a validation gate.",
    "citation": "lint:missing_validation_commands",
}


class PlanPrepareRoleContractTests(unittest.TestCase):
    def test_plan_review_and_normalizer_fragments_load(self) -> None:
        self.assertEqual(load_fragment("plan-review")["role"], "plan-review")
        self.assertEqual(load_fragment("plan-normalizer")["role"], "plan-normalizer")

    def test_plan_review_finding_shape_validates(self) -> None:
        self.assertEqual(validate_plan_review_finding(BLOCKING_FINDING), BLOCKING_FINDING)

    def test_plan_review_finding_rejects_unknown_severity(self) -> None:
        finding = dict(BLOCKING_FINDING)
        finding["severity"] = "critical"
        with self.assertRaisesRegex(ValueError, "severity"):
            validate_plan_review_finding(finding)

    def test_review_loop_stops_when_findings_are_non_blocking(self) -> None:
        result = run_plan_review_loop(
            "### Phase 1: Test",
            lint_runner=lambda _text: [],
            review_runner=lambda _text, _lint: [
                {
                    "severity": "advisory",
                    "phase_id": None,
                    "location": "plan",
                    "reason": "Small copy improvement.",
                    "citation": "plan",
                }
            ],
            normalizer_runner=lambda text, _lint, _fixes: text + "\nnormalized",
        )
        self.assertEqual(result.status, STATUS_READY)
        self.assertEqual(result.review_iteration_count, 1)
        self.assertEqual(result.prepared_plan_text, "### Phase 1: Test")

    def test_review_loop_caps_at_three_blocking_iterations(self) -> None:
        normalizer_calls: list[str] = []

        def normalize(text: str, _lint: list[dict], _fixes: list[dict]) -> str:
            normalizer_calls.append(text)
            return text + "\nnormalized"

        result = run_plan_review_loop(
            "### Phase 3: Test",
            lint_runner=lambda _text: [],
            review_runner=lambda _text, _lint: [BLOCKING_FINDING],
            normalizer_runner=normalize,
        )

        self.assertEqual(result.status, STATUS_NEEDS_INPUT)
        self.assertEqual(result.review_iteration_count, 3)
        self.assertEqual(len(result.review_findings), 3)
        self.assertEqual(len(normalizer_calls), 2)


if __name__ == "__main__":
    unittest.main()
