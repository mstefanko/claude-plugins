from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.permissions import (
    ROLE_NAMES,
    diff_role,
    load_fragment,
    load_settings,
    merge_role,
    permission_dir,
    uninstall_role,
    write_settings_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO_ROOT / "schemas" / "permissions.schema.json"
ROLE_SPECS_DIR = REPO_ROOT / "role-specs"

ROLE_SPEC_FORBIDDEN_PERMISSIONS = {
    "analysis": {"Grep", "Glob", "Edit", "Write", "Bash(rg:*)"},
    "analysis-judge": {"Grep", "Glob", "Edit", "Write", "Bash(rg:*)"},
    "clarify": {"Read", "Grep", "Glob", "Edit", "Write", "Bash(rg:*)"},
    "debug": {"Grep", "Glob", "Edit", "Write", "Bash(rg:*)"},
    "plan-review": {"Edit", "Write"},
    "research-merge": {"Grep", "Glob", "Edit", "Write", "Bash(rg:*)"},
}


class PermissionPresetTests(unittest.TestCase):
    def test_all_registered_fragments_load(self) -> None:
        for role in sorted(ROLE_NAMES):
            with self.subTest(role=role):
                fragment = load_fragment(role)
                self.assertEqual(fragment["role"], role)

    def test_role_registry_schema_and_fragments_stay_in_lockstep(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schema_roles = set(schema["properties"]["role"]["enum"])
        fragment_roles = {path.stem for path in permission_dir().glob("*.json")}

        self.assertEqual(ROLE_NAMES, schema_roles)
        self.assertEqual(ROLE_NAMES, fragment_roles)

    def test_registered_role_specs_with_fragments_load(self) -> None:
        for spec_path in sorted(ROLE_SPECS_DIR.glob("agent-*.md")):
            role = spec_path.stem.replace("agent-", "", 1)
            if role not in ROLE_NAMES:
                continue
            with self.subTest(role=role):
                self.assertEqual(load_fragment(role)["role"], role)

    def test_fragments_do_not_allow_tools_the_role_specs_forbid(self) -> None:
        for role, forbidden in sorted(ROLE_SPEC_FORBIDDEN_PERMISSIONS.items()):
            with self.subTest(role=role):
                allow = set(load_fragment(role)["permissions"].get("allow", []))
                self.assertFalse(
                    allow & forbidden,
                    f"{role} allows tools its role contract forbids: {sorted(allow & forbidden)}",
                )

    def test_clean_review_and_advisor_fragments_do_not_allow_sed(self) -> None:
        for role in ("clean-review", "implementation-advisor"):
            with self.subTest(role=role):
                allow = load_fragment(role)["permissions"]["allow"]
                self.assertNotIn("Bash(sed:*)", allow)

    def test_clarify_fragment_denies_source_reads_and_search(self) -> None:
        permissions = load_fragment("clarify")["permissions"]
        self.assertEqual(permissions["allow"], ["Bash(bd:*)"])
        for rule in ("Read", "Grep", "Glob", "Bash(rg:*)"):
            self.assertIn(rule, permissions["deny"])

    def test_notes_only_roles_deny_source_search_by_default(self) -> None:
        for role in ("analysis", "analysis-judge", "debug", "research-merge"):
            with self.subTest(role=role):
                permissions = load_fragment(role)["permissions"]
                self.assertNotIn("Bash(rg:*)", permissions["allow"])
                self.assertIn("Grep", permissions["deny"])
                self.assertIn("Glob", permissions["deny"])
                self.assertIn("Bash(rg:*)", permissions["deny"])

    def test_writer_fragment_reports_missing_rules_then_merges(self) -> None:
        fragment = load_fragment("writer")
        settings = {"permissions": {"allow": ["Read"]}}
        diff = diff_role(settings, fragment)
        self.assertIn("Write", diff.missing_allow)

        merged = merge_role(settings, fragment)
        self.assertIn("Write", merged["permissions"]["allow"])
        self.assertEqual(diff_role(merged, fragment).missing_allow, [])

    def test_conflicting_deny_rule_blocks_merge(self) -> None:
        fragment = load_fragment("writer")
        settings = {"permissions": {"deny": ["Write"]}}
        diff = diff_role(settings, fragment)
        self.assertEqual(diff.conflicts, ["Write"])
        with self.assertRaisesRegex(ValueError, "conflicting"):
            merge_role(settings, fragment)

    def test_uninstall_removes_only_fragment_rules(self) -> None:
        fragment = load_fragment("writer")
        settings = {"permissions": {"allow": ["Read", "Custom"]}}
        updated = uninstall_role(settings, fragment)
        self.assertEqual(updated["permissions"]["allow"], ["Custom"])

    def test_atomic_write_keeps_backup_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.local.json"
            path.write_text(json.dumps({"permissions": {"allow": ["Read"]}}), encoding="utf-8")
            backup = write_settings_atomic(path, {"permissions": {"allow": ["Read", "Write"]}})
            self.assertTrue(backup.is_file())
            loaded = load_settings(path)
            self.assertEqual(loaded["permissions"]["allow"], ["Read", "Write"])


if __name__ == "__main__":
    unittest.main()
