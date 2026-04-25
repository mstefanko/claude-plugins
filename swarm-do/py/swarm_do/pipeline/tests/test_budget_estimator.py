from __future__ import annotations

import unittest

from swarm_do.pipeline.budget import budget_lint_errors, estimate_unit_budget


class BudgetEstimatorTests(unittest.TestCase):
    def test_estimator_uses_conservative_linear_model(self) -> None:
        estimate = estimate_unit_budget(
            {
                "allowed_files": ["a.py", "b.py"],
                "acceptance_criteria": ["a", "b", "c"],
            }
        )
        self.assertEqual(estimate.tool_call_estimate, 22)
        self.assertEqual(estimate.output_byte_estimate, 5000)

    def test_budget_lint_reports_ceiling_breach(self) -> None:
        errors = budget_lint_errors(
            {"id": "unit-a", "allowed_files": ["a.py"], "acceptance_criteria": ["a"]},
            max_writer_tool_calls=1,
            max_writer_output_bytes=1,
        )
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
