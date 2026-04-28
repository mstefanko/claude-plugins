from __future__ import annotations

import unittest

from swarm_do.telemetry.permissions_contract import (
    compute_contract_usage,
    derive_allowed_categories,
    derive_denied_categories,
    load_permission_fragment,
)
from swarm_do.telemetry.subcommands.contract_usage import aggregate_contract_usage


class PermissionContractTests(unittest.TestCase):
    def test_research_fragment_loads_and_derives_categories(self) -> None:
        fragment = load_permission_fragment("research")
        self.assertIsNotNone(fragment)
        allowed = derive_allowed_categories(fragment)
        # research.json allows Read + Bash(bd:*) + Bash(rg:*) + Bash(find:*) + Bash(sed:*)
        self.assertIn("read", allowed)
        self.assertIn("shell-bd", allowed)
        self.assertIn("shell-rg", allowed)

    def test_unknown_role_returns_unknown_contract(self) -> None:
        usage = compute_contract_usage("agent-does-not-exist", {"read": 3})
        self.assertTrue(usage["unknown_contract"])
        self.assertEqual(usage["violations"], [])

    def test_violation_when_using_disallowed_category(self) -> None:
        # Synthetic fragment: allow Read only.
        fragment = {
            "schema_version": 1,
            "role": "synthetic",
            "permissions": {"allow": ["Read"], "deny": []},
        }
        usage = compute_contract_usage(
            "agent-synthetic",
            {"read": 4, "edit": 2, "search": 1},
            fragment=fragment,
        )
        violations = {(v["category"], v["reason"]) for v in usage["violations"]}
        self.assertIn(("edit", "not_allowed"), violations)
        self.assertIn(("search", "not_allowed"), violations)
        self.assertNotIn(("read", "not_allowed"), violations)

    def test_explicit_deny_marks_violation(self) -> None:
        fragment = {
            "schema_version": 1,
            "role": "synthetic",
            "permissions": {"allow": ["Read", "Edit"], "deny": ["Edit"]},
        }
        usage = compute_contract_usage(
            "agent-synthetic", {"edit": 1}, fragment=fragment
        )
        self.assertEqual(usage["violations"][0]["reason"], "denied")


class AggregateContractUsageTests(unittest.TestCase):
    def test_aggregates_violations_across_observations(self) -> None:
        rows = [
            {
                "run_id": "01ABCDEFGHJKMNPQRSTVWXYZ12",
                "details": {
                    "role": "agent-research",
                    "stage_id": "agent-research",
                    "tool_category_counts": {"read": 2, "shell-rg": 1, "edit": 1},
                },
            },
            {
                "run_id": "01ABCDEFGHJKMNPQRSTVWXYZ34",
                "details": {
                    "role": "agent-research",
                    "stage_id": "agent-research",
                    "tool_category_counts": {"read": 5, "shell-rg": 2},
                },
            },
        ]

        report = aggregate_contract_usage(rows, role="agent-research")

        self.assertEqual(report["summary"]["run_count"], 2)
        self.assertEqual(report["summary"]["violating_run_count"], 1)
        # research permissions don't allow `edit`, so the first row should violate.
        first = report["runs"][0]
        self.assertTrue(first["violations"])
        self.assertEqual(first["violations"][0]["category"], "edit")


if __name__ == "__main__":
    unittest.main()
