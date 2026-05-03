from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

from swarm_do.pipeline.execution_worktree import (
    RunExecutionWorktreeAdoptionBlocked,
    RunExecutionWorktreeError,
    RunExecutionWorktreeRebuildRequired,
    adopt_run_worktree,
    cleanup_run_worktree,
    execution_branch_name,
    initialize_unit_sessions,
    integrate_run_worktree,
    integration_branch_name,
    materialize_run_execution_worktree,
    materialize_unit_execution_worktree,
    merge_unit_execution_worktree,
    record_unit_post_writer_report,
    record_unit_spec_review_verdict,
    reset_run_worktree,
    resolve_run_execution_worktree,
    run_worktree_status,
    unit_execution_branch_name,
    unit_execution_worktree_root,
    validate_run_execution_worktree_manifest,
)
from swarm_do.pipeline.prepare import accept_prepared, prepare_plan_run
from swarm_do.pipeline.unit_sessions import load_unit_sessions, replace_unit_session, write_unit_sessions


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class ExecutionWorktreeTests(unittest.TestCase):
    def test_monorepo_subdir_mapping_and_artifact_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)

            resolved = resolve_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            self.assertEqual(resolved.source_git_root, git_root.resolve(strict=False))
            self.assertEqual(resolved.project_subdir, "swarm-do")
            self.assertEqual(resolved.safe_git_root, (data / "worktrees" / RUN_ID / "repo").resolve(strict=False))
            self.assertEqual(resolved.safe_project_root, (data / "worktrees" / RUN_ID / "repo" / "swarm-do").resolve(strict=False))

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            self.assertEqual(worktree.branch, execution_branch_name(RUN_ID))
            self.assertTrue((worktree.safe_project_root / "data" / "runs" / RUN_ID / "prepared.md").is_file())
            copied_prepared = json.loads(
                (worktree.safe_project_root / "data" / "runs" / RUN_ID / "prepared_plan.v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(copied_prepared["repo_root"], str(worktree.safe_project_root))
            manifest = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_git_root"], str(git_root.resolve(strict=False)))
            self.assertEqual(manifest["safe_project_root"], str(worktree.safe_project_root))
            self.assertGreaterEqual(len(manifest["copied_artifacts"]), 3)

    def test_dispatcher_policy_settings_are_scrubbed_from_writer_worktree(self) -> None:
        # The source-tree .claude/settings.local.json holds the dispatcher's coordinator
        # minimum allowlist and must not follow into a writer worktree, where Claude Code
        # would merge it on launch and override --allowedTools deny-wins.
        deny_writer_policy = {
            "permissions": {
                "allow": ["Bash(bd:*)", "Read"],
                "deny": ["Bash(rg:*)", "Edit", "Glob", "Grep", "Write"],
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(
                root, dispatcher_policy=deny_writer_policy
            )
            source_policy = project / ".claude" / "settings.local.json"
            self.assertTrue(source_policy.is_file(), "fixture must seed source policy file")

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            for rel in (".claude/settings.local.json", ".claude/settings.local.json.bak"):
                self.assertFalse(
                    (worktree.safe_project_root / rel).exists(),
                    f"{rel} must be removed from writer worktree",
                )

            status_lines = subprocess.run(
                ["git", "status", "--porcelain", "--", "swarm-do/.claude/"],
                cwd=worktree.safe_git_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertEqual(
                [line for line in status_lines if line.strip()],
                [],
                "skip-worktree must hide the scrub from git status",
            )

            self.assertEqual(
                json.loads(source_policy.read_text(encoding="utf-8")),
                deny_writer_policy,
                "scrub must not mutate source-tree dispatcher policy",
            )

    def test_sensitive_data_dir_uses_external_checkout_and_control_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(Path(td) / "xdg")}):
            root = Path(td)
            git_root, project, data, _prepared = _prepared_monorepo(root)
            sensitive = root / "home" / ".claude"
            sensitive_data = sensitive / "state"
            shutil.copytree(data, sensitive_data)
            prepared = json.loads((sensitive_data / "runs" / RUN_ID / "prepared_plan.v1.json").read_text(encoding="utf-8"))

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=sensitive_data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(sensitive)],
            )

            self.assertEqual(worktree.source_git_root, git_root.resolve(strict=False))
            self.assertEqual(worktree.manifest_path, sensitive_data / "worktrees" / RUN_ID / "manifest.json")
            self.assertTrue(worktree.manifest_path.is_file())
            self.assertFalse(str(worktree.safe_git_root).startswith(str(sensitive)))
            self.assertTrue(str(worktree.safe_git_root).startswith(str((root / "xdg").resolve(strict=False))))

    def test_artifact_copy_rejects_symlinked_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            descriptor = prepared["inspect_artifact"]
            source = project / descriptor["path"]
            target = source.with_name("inspect-target.json")
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            source.unlink()
            source.symlink_to(target)

            with self.assertRaisesRegex(RunExecutionWorktreeError, "symlink"):
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

    def test_top_level_project_mapping_uses_safe_git_root_as_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_top_level(root)

            resolved = resolve_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            self.assertEqual(resolved.source_git_root, git_root.resolve(strict=False))
            self.assertEqual(resolved.project_subdir, "")
            self.assertEqual(resolved.safe_project_root, resolved.safe_git_root)

    def test_dirty_source_project_scope_overlap_blocks_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            (project / "docs").mkdir()
            (project / "docs" / "new.md").write_text("dirty\n", encoding="utf-8")

            with self.assertRaises(RunExecutionWorktreeError) as raised:
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertIn("docs/new.md", str(raised.exception))

    def test_dirty_source_project_sibling_blocks_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            (project / "docs").mkdir()
            (project / "docs" / "helper.md").write_text("dirty\n", encoding="utf-8")

            with self.assertRaises(RunExecutionWorktreeError) as raised:
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertIn("docs/helper.md", str(raised.exception))

    def test_dirty_source_project_glob_parent_blocks_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            prepared = dict(prepared)
            descriptor = next(iter(prepared["work_unit_artifacts"].values()))
            descriptor["artifact"]["work_units"][0]["allowed_files"] = ["docs/*.md"]
            (project / "docs").mkdir()
            (project / "docs" / "helper.py").write_text("dirty\n", encoding="utf-8")

            with self.assertRaises(RunExecutionWorktreeError) as raised:
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertIn("docs/helper.py", str(raised.exception))

    def test_unrelated_dirty_markdown_does_not_block_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            (project / "planning").mkdir()
            (project / "planning" / "notes.md").write_text("dirty\n", encoding="utf-8")

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            self.assertTrue(worktree.safe_project_root.is_dir())
            self.assertFalse((worktree.safe_project_root / "planning" / "notes.md").exists())
            self.assertEqual(worktree.source_dirty_ignored_paths, ("planning/notes.md",))
            self.assertEqual(worktree.to_metadata()["source_dirty_ignored_paths"], ["planning/notes.md"])

    def test_dirty_source_plan_is_copied_into_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root, dirty_plan_before_prepare=True)

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            copied_plan = (worktree.safe_project_root / "plan.md").read_text(encoding="utf-8")
            self.assertIn("Dirty planning note", copied_plan)

    def test_unignored_copied_run_artifacts_do_not_dirty_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, _project, data, prepared = _prepared_monorepo(root, ignore_run_artifacts=False)

            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=Path(prepared["repo_root"]),
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            dry_run = adopt_run_worktree(RUN_ID, data_dir=data)

            self.assertTrue(worktree.safe_project_root.is_dir())
            self.assertTrue(dry_run["blocked_paths"])
            self.assertTrue(all(item["path"].startswith("data/runs/") for item in dry_run["blocked_paths"]))
            self.assertEqual(dry_run["copyback_operations"], [])

    def test_submodule_and_sparse_checkout_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            child = root / "child"
            super_repo = root / "home" / ".claude" / "plugins" / "super"
            _init_seed_repo(child)
            _init_seed_repo(super_repo)
            _git(super_repo, "-c", "protocol.file.allow=always", "submodule", "add", str(child), "modules/child")
            _git(super_repo, "commit", "-q", "-m", "add submodule")
            submodule = super_repo / "modules" / "child"
            submodule_prepared = {"git_base_sha": _git(submodule, "rev-parse", "HEAD"), "prepared_plan_path": "data/runs/x/prepared.md"}

            with self.assertRaisesRegex(RunExecutionWorktreeError, "submodule"):
                resolve_run_execution_worktree(
                    RUN_ID,
                    source_project_root=submodule,
                    data_dir=root / "data",
                    prepared_plan=submodule_prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            _git(super_repo, "config", "core.sparseCheckout", "true")
            sparse_prepared = {"git_base_sha": _git(super_repo, "rev-parse", "HEAD"), "prepared_plan_path": "data/runs/x/prepared.md"}
            with self.assertRaisesRegex(RunExecutionWorktreeError, "sparse-checkout"):
                resolve_run_execution_worktree(
                    RUN_ID,
                    source_project_root=super_repo,
                    data_dir=root / "data",
                    prepared_plan=sparse_prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

    def test_existing_execution_branch_is_not_reset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            (project / "wrong-base.txt").write_text("wrong base\n", encoding="utf-8")
            _git(git_root, "add", "swarm-do/wrong-base.txt")
            _git(git_root, "commit", "-q", "-m", "wrong base")
            wrong_sha = _git(git_root, "rev-parse", "HEAD")
            _git(git_root, "branch", execution_branch_name(RUN_ID), wrong_sha)

            with self.assertRaisesRegex(RunExecutionWorktreeError, "branch already exists"):
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertEqual(_git(git_root, "rev-parse", execution_branch_name(RUN_ID)), wrong_sha)

    def test_clean_base_drift_rebuilds_run_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            first = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            old_safe_root = first.safe_git_root
            (project / "after.txt").write_text("after\n", encoding="utf-8")
            _git(git_root, "add", "swarm-do/after.txt")
            _git(git_root, "commit", "-q", "-m", "advance source")
            new_sha = _git(git_root, "rev-parse", "HEAD")
            prepared = dict(prepared)
            prepared["git_base_sha"] = new_sha

            second = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            self.assertEqual(second.base_sha, new_sha)
            self.assertEqual(second.safe_git_root, old_safe_root)
            manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["base_sha"], new_sha)
            events = _read_run_events(data)
            self.assertIn("worktree_rebuilt", [event["event_type"] for event in events])

    def test_base_drift_with_unadopted_commit_requires_input(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "writer.md").write_text("writer\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "docs/writer.md")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "writer work")
            writer_sha = _git(worktree.safe_project_root, "rev-parse", "HEAD")
            (project / "after.txt").write_text("after\n", encoding="utf-8")
            _git(git_root, "add", "swarm-do/after.txt")
            _git(git_root, "commit", "-q", "-m", "advance source")
            prepared = dict(prepared)
            prepared["git_base_sha"] = _git(git_root, "rev-parse", "HEAD")

            with self.assertRaises(RunExecutionWorktreeRebuildRequired) as raised:
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertIn(writer_sha, raised.exception.unadopted_commits)
            self.assertTrue(worktree.safe_git_root.exists())

    def test_worktree_status_and_reset_archive_branch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "writer.md").write_text("writer\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "docs/writer.md")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "writer work")

            status = run_worktree_status(RUN_ID, data_dir=data)
            self.assertEqual(status["status"], "drift")
            self.assertEqual(len(status["unadopted_commits"]), 1)
            with self.assertRaises(RunExecutionWorktreeRebuildRequired):
                reset_run_worktree(RUN_ID, data_dir=data, archive_branch=True)

            reset = reset_run_worktree(RUN_ID, data_dir=data, archive_branch=True, force=True)

            self.assertTrue(reset["archived_branch"].startswith(execution_branch_name(RUN_ID) + ".archived-"))
            self.assertFalse(worktree.safe_git_root.exists())
            self.assertFalse(worktree.manifest_path.exists())
            self.assertEqual(_git(git_root, "rev-parse", reset["archived_branch"]).strip(), status["unadopted_commits"][0])

    def test_identity_mismatch_still_hard_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            payload = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            payload["run_id"] = "01BRZ3NDEKTSV4RRFFQ69G5FAV"
            worktree.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(RunExecutionWorktreeError, "manifest does not match this run"):
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

    def test_concurrent_runs_use_distinct_worktrees_and_branches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            other_run_id = "01BRZ3NDEKTSV4RRFFQ69G5FAV"
            other_prepared = _prepare_existing_project(project, data, other_run_id)

            first = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            second = materialize_run_execution_worktree(
                other_run_id,
                source_project_root=project,
                data_dir=data,
                prepared_plan=other_prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            self.assertNotEqual(first.safe_git_root, second.safe_git_root)
            self.assertNotEqual(first.branch, second.branch)
            self.assertTrue(first.safe_git_root.is_dir())
            self.assertTrue(second.safe_git_root.is_dir())

    def test_adopt_run_dry_run_apply_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "new.md").write_text("new\n", encoding="utf-8")

            dry_run = adopt_run_worktree(RUN_ID, data_dir=data)
            self.assertFalse(dry_run["applied"])
            self.assertEqual(dry_run["changed_files"], ["docs/new.md"])
            self.assertEqual(
                dry_run["copyback_operations"][0]["destination_path"],
                str((project / "docs" / "new.md").resolve(strict=False)),
            )
            self.assertFalse((project / "docs" / "new.md").exists())

            applied = adopt_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertTrue(applied["applied"])
            self.assertEqual((project / "docs" / "new.md").read_text(encoding="utf-8"), "new\n")

            cleanup = cleanup_run_worktree(RUN_ID, data_dir=data)
            self.assertTrue(cleanup["eligible"])
            cleanup_applied = cleanup_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertTrue(cleanup_applied["applied"])
            self.assertFalse(worktree.safe_git_root.exists())

    def test_adopt_run_handles_git_rename_as_delete_and_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            _git(worktree.safe_project_root, "mv", "plan.md", "plan-renamed.md")

            dry_run = adopt_run_worktree(RUN_ID, data_dir=data)
            operations = {(item["action"], item["path"]) for item in dry_run["copyback_operations"]}

            self.assertIn(("delete", "plan.md"), operations)
            self.assertIn(("copy", "plan-renamed.md"), operations)
            adopt_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertFalse((project / "plan.md").exists())
            self.assertIn("### Phase 1: Tiny", (project / "plan-renamed.md").read_text(encoding="utf-8"))

    def test_cleanup_preserves_unadopted_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            dry_run = cleanup_run_worktree(RUN_ID, data_dir=data)

            self.assertFalse(dry_run["eligible"])
            self.assertIn("unadopted", dry_run["preserved_reason"])
            with self.assertRaisesRegex(RunExecutionWorktreeError, "unadopted"):
                cleanup_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertTrue(worktree.safe_git_root.exists())

    def test_manifest_schema_requires_roots_branch_base_and_artifacts(self) -> None:
        with self.assertRaisesRegex(RunExecutionWorktreeError, "missing required property"):
            validate_run_execution_worktree_manifest({"schema_version": 1, "run_id": RUN_ID})

    def test_manifest_schema_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            payload = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            payload["surprise"] = True
            worktree.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(RunExecutionWorktreeError, "unexpected property 'surprise'"):
                adopt_run_worktree(RUN_ID, data_dir=data)

    def test_malformed_manifest_raises_worktree_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            worktree.manifest_path.write_text("{not json\n", encoding="utf-8")

            with self.assertRaisesRegex(RunExecutionWorktreeError, "manifest is not valid JSON"):
                adopt_run_worktree(RUN_ID, data_dir=data)

    def test_run_worktree_public_apis_reject_invalid_run_id_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)

            with self.assertRaisesRegex(RunExecutionWorktreeError, "invalid run_id"):
                materialize_run_execution_worktree(
                    "../not-a-run",
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                )
            with self.assertRaisesRegex(RunExecutionWorktreeError, "invalid run_id"):
                adopt_run_worktree("../not-a-run", data_dir=data)
            with self.assertRaisesRegex(RunExecutionWorktreeError, "invalid run_id"):
                integrate_run_worktree("../not-a-run", data_dir=data)
            with self.assertRaisesRegex(RunExecutionWorktreeError, "invalid run_id"):
                cleanup_run_worktree("../not-a-run", data_dir=data)
            with self.assertRaisesRegex(RunExecutionWorktreeError, "invalid run_id"):
                materialize_unit_execution_worktree("../not-a-run", "1", "unit-1", data_dir=data)

    def test_legacy_completed_manifest_migrates_to_complete_no_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            payload = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            payload["adoption_state"] = "completed"
            payload.pop("scope_check_path", None)
            worktree.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            dry_run = cleanup_run_worktree(RUN_ID, data_dir=data)

            self.assertTrue(dry_run["eligible"])
            self.assertEqual(dry_run["adoption_state"], "complete_no_changes")

    def test_cleanup_accepts_complete_no_changes_after_legacy_migration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            payload = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            payload["adoption_state"] = "completed"
            worktree.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            cleanup = cleanup_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertTrue(cleanup["applied"])
            self.assertFalse(worktree.safe_git_root.exists())

    def test_adopt_apply_blocks_dirty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "new.md").write_text("safe\n", encoding="utf-8")
            (project / "docs").mkdir()
            (project / "docs" / "new.md").write_text("dirty\n", encoding="utf-8")

            with self.assertRaisesRegex(RunExecutionWorktreeAdoptionBlocked, "destination_dirty") as raised:
                adopt_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertIn({"path": "docs/new.md", "reason": "destination_dirty"}, raised.exception.payload["blocked_paths"])

    def test_adopt_apply_blocks_destination_changed_since_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "plan.md").write_text("safe edit\n", encoding="utf-8")
            (project / "plan.md").write_text("source edit\n", encoding="utf-8")
            _git(git_root, "add", "swarm-do/plan.md")
            _git(git_root, "commit", "-q", "-m", "source changed after base")

            with self.assertRaisesRegex(RunExecutionWorktreeAdoptionBlocked, "destination_changed_since_base") as raised:
                adopt_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertIn(
                {"path": "plan.md", "reason": "destination_changed_since_base"},
                raised.exception.payload["blocked_paths"],
            )

    def test_adopt_apply_blocks_delete_directory_operation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "delete-dir").write_text("tracked in safe branch\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "docs/delete-dir")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "safe tracked file")
            (worktree.safe_project_root / "docs" / "delete-dir").unlink()
            (project / "docs" / "delete-dir").mkdir(parents=True)
            (project / "docs" / "delete-dir" / "child.txt").write_text("do not remove recursively\n", encoding="utf-8")

            with self.assertRaisesRegex(RunExecutionWorktreeAdoptionBlocked, "delete_directory") as raised:
                adopt_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertIn({"path": "docs/delete-dir", "reason": "delete_directory"}, raised.exception.payload["blocked_paths"])

    def test_adopt_dry_run_returns_scope_check_without_writing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "new.md").write_text("safe\n", encoding="utf-8")

            dry_run = adopt_run_worktree(RUN_ID, data_dir=data)

            self.assertIn("scope_check", dry_run)
            self.assertFalse((data / "worktrees" / RUN_ID / "scope-check.json").exists())

    def test_adopt_apply_writes_scope_check_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "new.md").write_text("safe\n", encoding="utf-8")

            applied = adopt_run_worktree(RUN_ID, data_dir=data, apply=True)

            scope_path = Path(applied["scope_check_path"])
            self.assertTrue(scope_path.is_file())
            manifest = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["scope_check_path"], str(scope_path))

    def test_adopt_apply_marks_complete_no_changes_when_no_operations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )

            applied = adopt_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertEqual(applied["adoption_state"], "complete_no_changes")
            manifest = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["adoption_state"], "complete_no_changes")

    def test_scope_check_blocks_explicit_blocked_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            _add_prepared_blocked_file(data, RUN_ID, "docs/secret.md")
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "secret.md").write_text("secret\n", encoding="utf-8")

            dry_run = adopt_run_worktree(RUN_ID, data_dir=data)

            self.assertIn({"path": "docs/secret.md", "reason": "blocked_files"}, dry_run["blocked_paths"])
            record = dry_run["scope_check"]["changed_files"][0]
            self.assertEqual(record["decision"], "block")
            self.assertEqual(record["matched_blocked_patterns"], ["docs/secret.md"])

    def test_integrate_run_dry_run_reports_execution_and_integration_branches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "new.md").write_text("safe\n", encoding="utf-8")

            dry_run = integrate_run_worktree(RUN_ID, data_dir=data)

            self.assertFalse(dry_run["applied"])
            self.assertEqual(dry_run["execution_branch"], execution_branch_name(RUN_ID))
            self.assertEqual(dry_run["integration_branch"], integration_branch_name(RUN_ID))
            self.assertEqual(dry_run["changed_files"], ["docs/new.md"])
            self.assertIn("scope_check", dry_run)
            self.assertIn("git -C", dry_run["predicted_merge_command"])
            self.assertFalse((data / "worktrees" / RUN_ID / "integration").exists())

    def test_integrate_run_apply_blocks_dirty_execution_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "dirty.md").write_text("dirty\n", encoding="utf-8")

            with self.assertRaisesRegex(RunExecutionWorktreeAdoptionBlocked, "dirty paths") as raised:
                integrate_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertIn(
                {"path": "docs/dirty.md", "reason": "execution_worktree_dirty"},
                raised.exception.payload["blocked_paths"],
            )
            self.assertFalse((data / "worktrees" / RUN_ID / "integration").exists())

    def test_integrate_run_apply_merges_execution_into_data_dir_integration_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            _clear_validation_commands(data, RUN_ID)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "integrated.md").write_text("integrated\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "docs/integrated.md")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "execution change")

            applied = integrate_run_worktree(RUN_ID, data_dir=data, apply=True)

            integration_project = Path(applied["integration_project_root"])
            self.assertTrue(applied["applied"])
            self.assertEqual(applied["status"], "integrated")
            self.assertEqual((integration_project / "docs" / "integrated.md").read_text(encoding="utf-8"), "integrated\n")
            self.assertFalse((project / "docs" / "integrated.md").exists())
            manifest = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["integration_manifest_path"], applied["integration_manifest_path"])
            adopt_dry_run = adopt_run_worktree(RUN_ID, data_dir=data)
            self.assertEqual(adopt_dry_run["adoption_source"], "integration")
            self.assertEqual(adopt_dry_run["changed_files"], ["docs/integrated.md"])
            adopted = adopt_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertEqual(adopted["adoption_source"], "integration")
            self.assertEqual((project / "docs" / "integrated.md").read_text(encoding="utf-8"), "integrated\n")
            cleanup = cleanup_run_worktree(RUN_ID, data_dir=data, apply=True)
            removed = {str(Path(path).resolve(strict=False)) for path in cleanup["removed"]}
            self.assertIn(str(integration_project.parent.resolve(strict=False)), removed)
            self.assertFalse(integration_project.parent.exists())

    def test_integrate_run_conflict_writes_conflict_manifest_and_preserves_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            _clear_validation_commands(data, RUN_ID)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "plan.md").write_text("execution edit\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "plan.md")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "execution edits plan")
            seed = root / "seed-integration"
            _git(git_root, "branch", integration_branch_name(RUN_ID), prepared["git_base_sha"])
            _git(git_root, "worktree", "add", str(seed), integration_branch_name(RUN_ID))
            (seed / "swarm-do" / "plan.md").write_text("integration edit\n", encoding="utf-8")
            _git(seed, "add", "swarm-do/plan.md")
            _git(seed, "commit", "-q", "-m", "integration edits plan")
            _git(git_root, "worktree", "remove", str(seed))

            result = integrate_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertEqual(result["status"], "conflicted")
            conflict_path = Path(result["conflict_manifest_path"])
            self.assertTrue(conflict_path.is_file())
            conflict = json.loads(conflict_path.read_text(encoding="utf-8"))
            self.assertIn("swarm-do/plan.md", conflict["conflicted_files"])
            cleanup = cleanup_run_worktree(RUN_ID, data_dir=data)
            self.assertFalse(cleanup["eligible"])
            self.assertIn("conflicted", cleanup["preserved_reason"])
            self.assertTrue(worktree.safe_git_root.exists())
            self.assertTrue(Path(result["integration_git_worktree_root"]).exists())

    def test_integrate_run_does_not_mutate_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            _clear_validation_commands(data, RUN_ID)
            source_head = _git(git_root, "rev-parse", "HEAD")
            source_status = _git(git_root, "status", "--porcelain=v1")
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "source-safe.md").write_text("not copied yet\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "docs/source-safe.md")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "execution source-safe")

            integrate_run_worktree(RUN_ID, data_dir=data, apply=True)

            self.assertEqual(_git(git_root, "rev-parse", "HEAD"), source_head)
            self.assertEqual(_git(git_root, "status", "--porcelain=v1"), source_status)
            self.assertFalse((project / "docs" / "source-safe.md").exists())

    def test_cleanup_preserves_conflicted_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            manifest = json.loads(worktree.manifest_path.read_text(encoding="utf-8"))
            manifest["adoption_state"] = "conflicted"
            worktree.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            cleanup = cleanup_run_worktree(RUN_ID, data_dir=data)

            self.assertFalse(cleanup["eligible"])
            with self.assertRaisesRegex(RunExecutionWorktreeError, "conflicted"):
                cleanup_run_worktree(RUN_ID, data_dir=data, apply=True)
            self.assertTrue(worktree.safe_git_root.exists())

    def test_unit_sessions_initialize_from_prepared_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)

            state = initialize_unit_sessions(RUN_ID, data_dir=data)

            self.assertEqual(state["run_id"], RUN_ID)
            self.assertEqual(len(state["units"]), 1)
            unit = state["units"][0]
            self.assertEqual(unit["phase_id"], phase_id)
            self.assertEqual(unit["unit_id"], unit_id)
            self.assertEqual(unit["branch"], unit_execution_branch_name(RUN_ID, phase_id, unit_id))
            self.assertEqual(unit["worktree_root"], str(unit_execution_worktree_root(data, RUN_ID, phase_id, unit_id).resolve(strict=False)))
            self.assertNotIn(".swarm-do/worktrees", unit["worktree_root"])
            self.assertIn("/home/.claude/", worktree.source_git_root.as_posix())
            self.assertEqual(load_unit_sessions(RUN_ID, data_dir=data)["units"][0]["writer_status"], "pending")

    def test_materialize_unit_worktree_uses_data_dir_root_and_copies_safe_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)

            payload = materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data)

            worktree_root = Path(payload["worktree_root"])
            project_root = Path(payload["project_root"])
            self.assertTrue(worktree_root.is_dir())
            self.assertEqual(worktree_root, unit_execution_worktree_root(data, RUN_ID, phase_id, unit_id).resolve(strict=False))
            self.assertNotIn(".swarm-do/worktrees", str(worktree_root))
            copied_prepared = json.loads(
                (project_root / "data" / "runs" / RUN_ID / "prepared_plan.v1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(copied_prepared["repo_root"], str(project_root))
            state_unit = load_unit_sessions(RUN_ID, data_dir=data)["units"][0]
            self.assertEqual(state_unit["project_root"], str(project_root))

    def test_materialize_unit_worktree_rolls_back_branch_on_add_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)
            branch = unit_execution_branch_name(RUN_ID, phase_id, unit_id)
            unit_root = unit_execution_worktree_root(data, RUN_ID, phase_id, unit_id).resolve(strict=False)
            from swarm_do.pipeline import execution_worktree as ew

            original_git = ew._git

            def failing_git(repo: Path, *args: str):
                if args[:2] == ("worktree", "add"):
                    original_git(git_root, "branch", branch, prepared["git_base_sha"])
                    raise RunExecutionWorktreeError("simulated add failure")
                return original_git(repo, *args)

            with mock.patch("swarm_do.pipeline.execution_worktree._git", side_effect=failing_git):
                with self.assertRaisesRegex(RunExecutionWorktreeError, "simulated add failure"):
                    materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data)

            self.assertEqual(_git(git_root, "branch", "--list", branch), "")
            self.assertFalse(unit_root.exists())

    def test_materialize_unit_worktree_can_branch_from_integration_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            _clear_validation_commands(data, RUN_ID)
            worktree = materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            (worktree.safe_project_root / "docs").mkdir()
            (worktree.safe_project_root / "docs" / "integrated-base.md").write_text("base\n", encoding="utf-8")
            _git(worktree.safe_project_root, "add", "docs/integrated-base.md")
            _git(worktree.safe_project_root, "commit", "-q", "-m", "execution base")
            integrated = integrate_run_worktree(RUN_ID, data_dir=data, apply=True)
            phase_id, unit_id = _first_unit(prepared)

            payload = materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data, base="integration")

            self.assertEqual(payload["base_ref"], integration_branch_name(RUN_ID))
            self.assertEqual(payload["base_sha"], integrated["integration_head_sha"])
            self.assertEqual((Path(payload["project_root"]) / "docs" / "integrated-base.md").read_text(encoding="utf-8"), "base\n")

    def test_unit_merge_requires_post_writer_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)
            materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data)

            with self.assertRaisesRegex(RunExecutionWorktreeAdoptionBlocked, "post-writer gate"):
                merge_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data, apply=True)

            state_unit = load_unit_sessions(RUN_ID, data_dir=data)["units"][0]
            self.assertEqual(state_unit["merge_state"], "blocked")

    def test_unit_post_writer_report_allows_merge_into_integration_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)
            unit = materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data)
            unit_project = Path(unit["project_root"])
            (unit_project / "docs").mkdir()
            (unit_project / "docs" / "unit.md").write_text("unit\n", encoding="utf-8")
            _git(unit_project, "add", "docs/unit.md")
            _git(unit_project, "commit", "-q", "-m", "unit change")
            report_path = _write_unit_report(data, RUN_ID, unit_id, gate_status="passed", changed_files=["docs/unit.md"])

            recorded = record_unit_post_writer_report(
                RUN_ID,
                phase_id,
                unit_id,
                data_dir=data,
                report_path=report_path,
            )
            record_unit_spec_review_verdict(RUN_ID, phase_id, unit_id, data_dir=data, verdict="skipped")
            merged = merge_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data, apply=True)

            self.assertEqual(recorded["writer_status"], "approved")
            self.assertEqual(merged["status"], "merged")
            integration_project = Path(merged["integration_project_root"])
            self.assertEqual((integration_project / "docs" / "unit.md").read_text(encoding="utf-8"), "unit\n")
            self.assertFalse((project / "docs" / "unit.md").exists())
            state_unit = load_unit_sessions(RUN_ID, data_dir=data)["units"][0]
            self.assertEqual(state_unit["merge_state"], "merged")
            self.assertEqual(state_unit["cleanup_state"], "cleanup_eligible")

    def test_unit_merge_does_not_overwrite_already_merged_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, _project, data, prepared = _prepared_monorepo(root)
            materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=Path(prepared["repo_root"]),
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)
            unit = materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data)
            unit_project = Path(unit["project_root"])
            (unit_project / "docs").mkdir()
            (unit_project / "docs" / "unit.md").write_text("unit\n", encoding="utf-8")
            _git(unit_project, "add", "docs/unit.md")
            _git(unit_project, "commit", "-q", "-m", "unit change")
            report_path = _write_unit_report(data, RUN_ID, unit_id, gate_status="passed", changed_files=["docs/unit.md"])
            record_unit_post_writer_report(RUN_ID, phase_id, unit_id, data_dir=data, report_path=report_path)
            record_unit_spec_review_verdict(RUN_ID, phase_id, unit_id, data_dir=data, verdict="skipped")

            def mark_already_merged(_integration_git: Path) -> list[str]:
                state = load_unit_sessions(RUN_ID, data_dir=data)
                current = state["units"][0]
                current.update(
                    {
                        "merge_state": "merged",
                        "cleanup_state": "cleanup_eligible",
                        "completed_at": "2026-04-29T00:00:00Z",
                    }
                )
                write_unit_sessions(
                    replace_unit_session(state, phase_id, unit_id, current),
                    data_dir=data,
                )
                return []

            with mock.patch(
                "swarm_do.pipeline.execution_worktree._conflicted_files",
                side_effect=mark_already_merged,
            ):
                result = merge_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data, apply=True)

            self.assertEqual(result["status"], "merged")
            state_unit = load_unit_sessions(RUN_ID, data_dir=data)["units"][0]
            self.assertEqual(state_unit["merge_state"], "merged")
            self.assertEqual(state_unit["completed_at"], "2026-04-29T00:00:00Z")

    def test_unit_merge_conflict_writes_unit_conflict_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_root, project, data, prepared = _prepared_monorepo(root)
            materialize_run_execution_worktree(
                RUN_ID,
                source_project_root=project,
                data_dir=data,
                prepared_plan=prepared,
                sensitive_prefixes=[str(root / "home" / ".claude")],
            )
            phase_id, unit_id = _first_unit(prepared)
            unit = materialize_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data)
            unit_project = Path(unit["project_root"])
            (unit_project / "plan.md").write_text("unit edit\n", encoding="utf-8")
            _git(unit_project, "add", "plan.md")
            _git(unit_project, "commit", "-q", "-m", "unit edits plan")
            seed = root / "seed-unit-integration"
            _git(git_root, "branch", integration_branch_name(RUN_ID), prepared["git_base_sha"])
            _git(git_root, "worktree", "add", str(seed), integration_branch_name(RUN_ID))
            (seed / "swarm-do" / "plan.md").write_text("integration edit\n", encoding="utf-8")
            _git(seed, "add", "swarm-do/plan.md")
            _git(seed, "commit", "-q", "-m", "integration edits plan")
            _git(git_root, "worktree", "remove", str(seed))
            report_path = _write_unit_report(data, RUN_ID, unit_id, gate_status="passed", changed_files=["plan.md"])
            record_unit_post_writer_report(RUN_ID, phase_id, unit_id, data_dir=data, report_path=report_path)
            record_unit_spec_review_verdict(RUN_ID, phase_id, unit_id, data_dir=data, verdict="skipped")

            result = merge_unit_execution_worktree(RUN_ID, phase_id, unit_id, data_dir=data, apply=True)

            self.assertEqual(result["status"], "conflicted")
            conflict_path = Path(result["conflict_manifest_path"])
            self.assertTrue(conflict_path.is_file())
            conflict = json.loads(conflict_path.read_text(encoding="utf-8"))
            self.assertEqual(conflict["unit_id"], unit_id)
            self.assertIn("swarm-do/plan.md", conflict["conflicted_files"])
            state_unit = load_unit_sessions(RUN_ID, data_dir=data)["units"][0]
            self.assertEqual(state_unit["merge_state"], "conflicted")
            self.assertEqual(state_unit["conflict_manifest_path"], str(conflict_path))


def _prepared_monorepo(
    root: Path,
    *,
    run_id: str = RUN_ID,
    ignore_run_artifacts: bool = True,
    dirty_plan_before_prepare: bool = False,
    dispatcher_policy: Mapping[str, Any] | None = None,
) -> tuple[Path, Path, Path, dict]:
    git_root = root / "home" / ".claude" / "plugins" / "mstefanko-plugins"
    project = git_root / "swarm-do"
    data = root / "data"
    project.mkdir(parents=True)
    data.mkdir()
    _git(git_root, "init", "-q", "-b", "main")
    add_paths = ["swarm-do/plan.md"]
    if ignore_run_artifacts:
        (project / ".gitignore").write_text("data/runs/\n", encoding="utf-8")
        add_paths.append("swarm-do/.gitignore")
    if dispatcher_policy is not None:
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.local.json").write_text(
            json.dumps(dispatcher_policy, indent=2) + "\n", encoding="utf-8"
        )
        (claude_dir / "settings.local.json.bak").write_text(
            json.dumps(dispatcher_policy, indent=2) + "\n", encoding="utf-8"
        )
        add_paths.extend(
            ["swarm-do/.claude/settings.local.json", "swarm-do/.claude/settings.local.json.bak"]
        )
    (project / "plan.md").write_text(
        (
            "### Phase 1: Tiny\n\n"
            "Do a tiny thing.\n\n"
            "### Files to create / modify\n"
            "- docs/new.md\n\n"
            "### Acceptance Criteria\n"
            "- Tiny thing is done.\n\n"
            "### Validation Commands\n"
            "- python3 -m unittest py.swarm_do.pipeline.tests.test_execution_worktree\n"
        ),
        encoding="utf-8",
    )
    _git(git_root, "add", *add_paths)
    _git(git_root, "commit", "-q", "-m", "seed")
    if dirty_plan_before_prepare:
        with (project / "plan.md").open("a", encoding="utf-8") as handle:
            handle.write("\nDirty planning note.\n")
    prepared = _prepare_existing_project(project, data, run_id)
    return git_root, project, data, prepared


def _prepared_top_level(root: Path) -> tuple[Path, Path, Path, dict]:
    project = root / "home" / ".claude" / "plugins" / "swarm-do"
    data = root / "data"
    project.mkdir(parents=True)
    data.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text("data/runs/\n", encoding="utf-8")
    (project / "plan.md").write_text(
        (
            "### Phase 1: Tiny\n\n"
            "Do a tiny thing.\n\n"
            "### Files to create / modify\n"
            "- docs/new.md\n\n"
            "### Acceptance Criteria\n"
            "- Tiny thing is done.\n\n"
            "### Validation Commands\n"
            "- python3 -m unittest py.swarm_do.pipeline.tests.test_execution_worktree\n"
        ),
        encoding="utf-8",
    )
    _git(project, "add", ".gitignore", "plan.md")
    _git(project, "commit", "-q", "-m", "seed")
    prepared = _prepare_existing_project(project, data, RUN_ID)
    return project, project, data, prepared


def _prepare_existing_project(project: Path, data: Path, run_id: str) -> dict:
    result = prepare_plan_run(
        "plan.md",
        run_id=run_id,
        repo_root=project,
        data_dir=data,
        decompose_workers=1,
    )
    if result.status != "ready_for_acceptance":
        raise AssertionError(result.to_dict())
    accept_prepared(run_id, repo_root=project, data_dir=data)
    return json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))


def _read_run_events(data: Path) -> list[dict]:
    path = data / "telemetry" / "run_events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _add_prepared_blocked_file(data: Path, run_id: str, pattern: str) -> None:
    path = data / "runs" / run_id / "prepared_plan.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    descriptor = payload["work_unit_artifacts"]["1"]
    artifact = descriptor["artifact"]
    artifact["work_units"][0]["blocked_files"] = [pattern]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clear_validation_commands(data: Path, run_id: str) -> None:
    path = data / "runs" / run_id / "prepared_plan.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for descriptor in payload.get("work_unit_artifacts", {}).values():
        if not isinstance(descriptor, dict):
            continue
        artifact = descriptor.get("artifact")
        if not isinstance(artifact, dict):
            continue
        for unit in artifact.get("work_units") or []:
            if isinstance(unit, dict):
                unit["validation_commands"] = []
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _first_unit(prepared: dict) -> tuple[str, str]:
    phase_id = next(iter(prepared["work_unit_artifacts"]))
    artifact = prepared["work_unit_artifacts"][phase_id]["artifact"]
    return str(phase_id), str(artifact["work_units"][0]["id"])


def _write_unit_report(data: Path, run_id: str, unit_id: str, *, gate_status: str, changed_files: list[str]) -> Path:
    path = data / "runs" / run_id / "unit_reports" / f"{unit_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "post_writer_report.v1",
                "work_unit_id": unit_id,
                "changed_files": changed_files,
                "gate": {"status": gate_status, "failure_reasons": [] if gate_status == "passed" else ["fixture"]},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _init_seed_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.test",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ).stdout.strip()


if __name__ == "__main__":
    unittest.main()
