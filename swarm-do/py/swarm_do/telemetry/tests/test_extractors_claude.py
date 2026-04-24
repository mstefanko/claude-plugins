"""Claude extractor tests — agent-review and agent-code-review formats.

Fixtures cover:
  - agent-review `### Issues Found` section (3 items; high/correctness)
  - agent-code-review `### Critical Issues` + `### Warnings` + `### Info`
    sections (5 items total, severity + category mapping per plan WS-3 table)

Stability check: calling extract() twice on the same fixture must produce
equal stable_finding_hash_v1 values (ULIDs differ; hashes stay pinned).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.telemetry.extractors.claude_review import extract


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "extractors"


class AgentReviewNotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FIXTURE_DIR / "agent_review_notes.md"
        self.assertTrue(self.fixture.is_file())

    def test_three_rows_emitted_from_issues_found(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNB0000000000000000000000",
            "agent-review",
            "test-issue-42",
        )
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["severity"], "high")
            self.assertEqual(row["category"], "correctness")
            self.assertEqual(row["role"], "agent-review")
            self.assertEqual(row["issue_id"], "test-issue-42")
            self.assertIsNotNone(row["stable_finding_hash_v1"])
            self.assertIsNotNone(row["file_path"])
            self.assertIsNotNone(row["line_start"])

    def test_hash_stability_across_reruns(self) -> None:
        args = (
            str(self.fixture),
            "RUNB0000000000000000000000",
            "agent-review",
            "test-issue-42",
        )
        first = extract(*args)
        second = extract(*args)
        self.assertEqual(len(first), len(second))
        for a, b in zip(first, second):
            self.assertEqual(a["stable_finding_hash_v1"], b["stable_finding_hash_v1"])
            self.assertNotEqual(a["finding_id"], b["finding_id"])

    def test_line_range_parsed_correctly(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNB0000000000000000000000",
            "agent-review",
            "test-issue-42",
        )
        # Second item is "pkg/parse/token.go:100-120"
        self.assertEqual(rows[1]["line_start"], 100)
        self.assertEqual(rows[1]["line_end"], 120)


class AgentCodeReviewNotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FIXTURE_DIR / "agent_code_review_notes.md"
        self.assertTrue(self.fixture.is_file())

    def test_emits_five_rows_across_four_sections(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNC0000000000000000000000",
            "agent-code-review",
            "test-issue-99",
        )
        # 2 critical + 2 warning + 1 info.
        self.assertEqual(len(rows), 5)

    def test_severity_mapping_per_section(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNC0000000000000000000000",
            "agent-code-review",
            "test-issue-99",
        )
        severities = [r["severity"] for r in rows]
        self.assertEqual(severities.count("critical"), 2)
        self.assertEqual(severities.count("medium"), 2)
        self.assertEqual(severities.count("info"), 1)

    def test_critical_category_infers_security_from_keywords(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNC0000000000000000000000",
            "agent-code-review",
            "test-issue-99",
        )
        critical_rows = [r for r in rows if r["severity"] == "critical"]
        # Both critical items have security-signal keywords (SQL injection, auth check).
        for row in critical_rows:
            self.assertEqual(row["category"], "security")

    def test_warning_category_is_tbd(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNC0000000000000000000000",
            "agent-code-review",
            "test-issue-99",
        )
        warnings = [r for r in rows if r["severity"] == "medium"]
        self.assertEqual(len(warnings), 2)
        for row in warnings:
            self.assertEqual(row["category"], "tbd")

    def test_info_category_is_observation(self) -> None:
        rows = extract(
            str(self.fixture),
            "RUNC0000000000000000000000",
            "agent-code-review",
            "test-issue-99",
        )
        info_rows = [r for r in rows if r["severity"] == "info"]
        self.assertEqual(len(info_rows), 1)
        self.assertEqual(info_rows[0]["category"], "observation")


class FailOpenTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        rows = extract("/nonexistent/path/to/notes.md", "RUN", "agent-review", "issue-x")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
