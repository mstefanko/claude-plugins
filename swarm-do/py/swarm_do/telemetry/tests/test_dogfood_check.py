from __future__ import annotations

import unittest

from swarm_do.telemetry.subcommands.dogfood_check import build_dogfood_check_report


class DogfoodCheckTests(unittest.TestCase):
    def test_holds_when_writer_runs_lack_post_writer_report(self) -> None:
        runs = [_run(idx) for idx in range(10)]
        observations = [
            {"run_id": row["run_id"], "event_type": "writer_exit", "details": {"source_read_count": 1}}
            for row in runs
        ]

        report = build_dogfood_check_report(
            runs,
            observations,
            [{"run_id": row["run_id"], "event_type": "prepare_dispatch_started"} for row in runs],
        )

        self.assertEqual(report["recommendation"], "HOLD")
        self.assertIn("missing_post_writer_report", {finding["code"] for finding in report["findings"]})

    def test_promote_candidate_when_required_evidence_is_present(self) -> None:
        runs = [_run(idx) for idx in range(10)]
        observations = [
            {
                "run_id": row["run_id"],
                "event_type": "writer_exit",
                "details": {
                    "source_read_count": 1,
                    "repeated_read_histogram": [],
                    "first_test_tool_call_index": 2,
                    "token_usage": {"cache_hit_ratio": 0.5},
                },
            }
            for row in runs
        ]
        events = []
        for row in runs:
            events.extend({"run_id": row["run_id"], "event_type": event_type} for event_type in _prepare_events())
            events.append(
                {
                    "run_id": row["run_id"],
                    "event_type": "post_writer_report",
                    "details": {"gate_status": "passed"},
                }
            )

        report = build_dogfood_check_report(runs, observations, events)

        self.assertEqual(report["recommendation"], "PROMOTE_CANDIDATE")
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["summary"]["post_writer_report_count"], 10)

    def test_flags_stale_reject_without_reason(self) -> None:
        runs = [_run(idx) for idx in range(10)]
        events = []
        for row in runs:
            events.extend({"run_id": row["run_id"], "event_type": event_type} for event_type in _prepare_events())
            events.append({"run_id": row["run_id"], "event_type": "post_writer_report"})
        events.append({"run_id": runs[0]["run_id"], "event_type": "prepare_stale_rejected", "details": {}})

        report = build_dogfood_check_report(runs, [{"run_id": row["run_id"], "details": {}} for row in runs], events)

        self.assertEqual(report["recommendation"], "HOLD")
        self.assertIn("stale_reject_without_reason", {finding["code"] for finding in report["findings"]})


def _run(idx: int) -> dict:
    return {
        "run_id": f"01ARZ3NDEKTSV4RRFFQ69G5{idx:02d}",
        "variant": "prep6.a",
        "role": "agent-writer",
        "phase_kind": "feature",
        "phase_complexity": "simple",
        "base_sha": "a" * 40,
        "unit_tool_call_count": 10,
    }


def _prepare_events() -> tuple[str, ...]:
    return (
        "prepare_started",
        "prepare_lint_findings",
        "prepare_review_findings",
        "prepare_safe_fixes_accepted",
        "prepare_safe_fixes_proposed_unaccepted",
        "prepare_ready_for_acceptance",
        "prepare_accepted",
        "prepare_dispatch_started",
    )


if __name__ == "__main__":
    unittest.main()
