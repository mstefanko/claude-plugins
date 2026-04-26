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
    uninstall_role,
    write_settings_atomic,
)


class PermissionPresetTests(unittest.TestCase):
    def test_all_registered_fragments_load(self) -> None:
        for role in sorted(ROLE_NAMES):
            with self.subTest(role=role):
                fragment = load_fragment(role)
                self.assertEqual(fragment["role"], role)

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
        fragment = load_fragment("clarify")
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
