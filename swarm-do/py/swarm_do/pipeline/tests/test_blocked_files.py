from __future__ import annotations

import unittest

from swarm_do.pipeline.validation import blocked_file_violations, schema_lint_work_units, unit_blocked_file_violations


class BlockedFilesTests(unittest.TestCase):
    def test_changed_file_matching_blocked_glob_is_reported(self) -> None:
        self.assertEqual(
            blocked_file_violations(["py/a.py", "docs/a.md"], ["py/*.py"]),
            ["py/a.py"],
        )

    def test_unit_blocked_file_violations_reads_v2_field(self) -> None:
        unit = {"blocked_files": ["secrets/**"]}
        self.assertEqual(unit_blocked_file_violations(unit, ["secrets/token.txt"]), ["secrets/token.txt"])

    def test_lint_rejects_blocked_allowed_overlap(self) -> None:
        artifact = {"schema_version": 2, "work_units": [v2_unit("unit-a")]}
        artifact["work_units"][0]["blocked_files"] = ["py/a.py"]
        lint = schema_lint_work_units(artifact)
        self.assertTrue(any("blocked_files overlaps allowed_files" in error for error in lint.errors))


def v2_unit(unit_id: str) -> dict:
    return {
        "id": unit_id,
        "title": unit_id,
        "goal": "goal",
        "depends_on": [],
        "context_files": [],
        "allowed_files": ["py/a.py"],
        "blocked_files": [],
        "acceptance_criteria": ["passes"],
        "validation_commands": [],
        "expected_results": [],
        "risk_tags": [],
        "handoff_notes": "",
        "beads_id": None,
        "worktree_branch": None,
        "status": "pending",
        "failure_reason": None,
        "retry_count": 0,
        "handoff_count": 0,
    }


if __name__ == "__main__":
    unittest.main()
