from __future__ import annotations

import unittest

from swarm_do.pipeline.executor import writer_budget_status


class WriterBudgetTests(unittest.TestCase):
    def test_mismatched_work_unit_id_escalates(self) -> None:
        status = writer_budget_status(
            {"id": "unit-a"},
            '{"work_unit_id":"unit-b","tool_calls":1,"output_bytes":1,"handoff":false,"summary":"done"}',
        )
        self.assertEqual(status["status"], "escalated")
        self.assertEqual(status["failure_reason"], "other")

    def test_tool_call_breach_escalates(self) -> None:
        status = writer_budget_status(
            {"id": "unit-a"},
            '{"work_unit_id":"unit-a","tool_calls":99,"output_bytes":1,"handoff":false,"summary":"done"}',
            max_writer_tool_calls=60,
        )
        self.assertEqual(status["status"], "escalated")
        self.assertEqual(status["failure_reason"], "budget_breach_tool_calls")
        self.assertEqual(status["tool_call_count"], 99)

    def test_missing_return_block_escalates(self) -> None:
        status = writer_budget_status({"id": "unit-a"}, "DONE")
        self.assertEqual(status["status"], "escalated")
        self.assertEqual(status["failure_reason"], "other")

    def test_codex_telemetry_wins_with_warning(self) -> None:
        status = writer_budget_status(
            {"id": "unit-a"},
            '{"work_unit_id":"unit-a","tool_calls":3,"output_bytes":1,"handoff":false,"summary":"done"}',
            telemetry_tool_call_count=10,
        )
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["tool_call_count"], 10)
        self.assertTrue(status["warnings"])


if __name__ == "__main__":
    unittest.main()
