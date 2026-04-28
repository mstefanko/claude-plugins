from __future__ import annotations

import unittest

from swarm_do.telemetry.subcommands.experiment_report import aggregate_experiment_report


class ExperimentReportTests(unittest.TestCase):
    def test_aggregates_scorecard_metrics_by_variant(self) -> None:
        runs = [
            {
                "run_id": "R1",
                "variant": "prep6.a",
                "role": "agent-writer",
                "phase_kind": "feature",
                "phase_complexity": "hard",
                "base_sha": "a" * 40,
                "work_unit_id": "unit-a",
                "unit_tool_call_count": 10,
                "wall_clock_seconds": 20,
                "input_tokens": 100,
                "cached_input_tokens": 50,
                "output_tokens": 30,
                "unit_handoff_count": 1,
                "unit_needs_context_count": 1,
                "review_verdict": "SPEC_MISMATCH",
            },
            {
                "run_id": "R2",
                "variant": "prep6.b",
                "role": "agent-review",
                "phase_kind": "feature",
                "phase_complexity": None,
                "base_sha": None,
                "tool_call_count": 8,
                "review_verdict": "NEEDS_CHANGES",
            },
        ]
        observations = [
            {
                "run_id": "R1",
                "event_type": "writer_exit",
                "details": {
                    "source_read_count": 3,
                    "repeated_read_histogram": [
                        {"file_path": "py/a.py", "count": 3}
                    ],
                    "first_test_tool_call_index": 4,
                    "markers": {
                        "needs_context_count": 1,
                        "needs_research_count": 2,
                    },
                    "token_usage": {"cache_hit_ratio": 0.5},
                },
            },
            {
                "run_id": "R2",
                "event_type": "docs_skipped",
                "details": {"doc_impact": False, "stage_id": "agent-docs"},
            },
        ]
        run_events = [
            {"run_id": "R1", "event_type": "prepare_dispatch_started"},
            {"run_id": "R1", "event_type": "prepare_stale_rejected"},
            {"run_id": "R2", "event_type": "retry_started"},
        ]

        report = aggregate_experiment_report(
            runs,
            observations,
            run_events,
            batch="batch-1",
        )

        self.assertEqual(report["batch"], "batch-1")
        self.assertEqual(report["summary"]["run_count"], 2)
        self.assertEqual(report["summary"]["observation_count"], 2)
        self.assertEqual(report["summary"]["run_event_count"], 3)
        self.assertEqual(report["summary"]["null_phase_tag_count"], 1)
        self.assertEqual(report["summary"]["null_base_sha_count"], 1)
        self.assertFalse(report["summary"]["controlled_comparison_ready"])
        self.assertIn("phase_tags", report["summary"]["unknown_safety_metrics"])
        self.assertIn("base_sha", report["summary"]["unknown_safety_metrics"])

        by_variant = {row["variant"]: row for row in report["by_variant"]}
        self.assertEqual(by_variant["prep6.a"]["mean_tool_calls"], 10)
        self.assertEqual(by_variant["prep6.a"]["p95_tool_calls"], 10)
        self.assertEqual(by_variant["prep6.a"]["mean_cache_hit_ratio"], 0.5)
        self.assertEqual(by_variant["prep6.a"]["mean_first_test_position"], 4)
        self.assertEqual(by_variant["prep6.a"]["source_read_count"], 3)
        self.assertEqual(by_variant["prep6.a"]["repeated_read_file_count"], 1)
        self.assertEqual(by_variant["prep6.a"]["repeated_read_extra_count"], 2)
        self.assertEqual(by_variant["prep6.a"]["needs_context_count"], 1)
        self.assertEqual(by_variant["prep6.a"]["needs_research_count"], 2)
        self.assertEqual(by_variant["prep6.a"]["handoff_count"], 1)
        self.assertEqual(by_variant["prep6.a"]["spec_mismatch_count"], 1)
        self.assertEqual(by_variant["prep6.a"]["prepare_dispatch_started_count"], 1)
        self.assertEqual(by_variant["prep6.a"]["prepare_stale_rejected_count"], 1)

        self.assertEqual(by_variant["prep6.b"]["review_failure_count"], 1)
        self.assertEqual(by_variant["prep6.b"]["retry_count"], 1)
        self.assertEqual(by_variant["prep6.b"]["doc_stage_skip_count"], 1)

    def test_variant_filter_limits_joined_rows(self) -> None:
        runs = [
            {"run_id": "R1", "variant": "A", "phase_kind": "feature", "phase_complexity": "simple", "base_sha": "a" * 40},
            {"run_id": "R2", "variant": "B", "phase_kind": "feature", "phase_complexity": "simple", "base_sha": "b" * 40},
        ]
        observations = [
            {"run_id": "R1", "event_type": "writer_exit", "details": {"source_read_count": 1}},
            {"run_id": "R2", "event_type": "writer_exit", "details": {"source_read_count": 9}},
        ]

        report = aggregate_experiment_report(
            runs,
            observations,
            [],
            variant="A",
        )

        self.assertEqual(report["summary"]["run_count"], 1)
        self.assertEqual(report["summary"]["variants"], ["A"])
        self.assertEqual(report["by_variant"][0]["source_read_count"], 1)


if __name__ == "__main__":
    unittest.main()
