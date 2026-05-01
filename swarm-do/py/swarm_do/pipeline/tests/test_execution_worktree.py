from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.execution_worktree import (
    RunExecutionWorktreeAdoptionBlocked,
    RunExecutionWorktreeError,
    adopt_run_worktree,
    cleanup_run_worktree,
    execution_branch_name,
    integrate_run_worktree,
    integration_branch_name,
    materialize_run_execution_worktree,
    resolve_run_execution_worktree,
    validate_run_execution_worktree_manifest,
)
from swarm_do.pipeline.prepare import accept_prepared, prepare_plan_run


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

    def test_dirty_source_project_blocks_safe_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_root, project, data, prepared = _prepared_monorepo(root)
            (project / "docs").mkdir()
            (project / "docs" / "dirty.md").write_text("dirty\n", encoding="utf-8")

            with self.assertRaises(RunExecutionWorktreeError) as raised:
                materialize_run_execution_worktree(
                    RUN_ID,
                    source_project_root=project,
                    data_dir=data,
                    prepared_plan=prepared,
                    sensitive_prefixes=[str(root / "home" / ".claude")],
                )

            self.assertIn("dirty.md", str(raised.exception))

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


def _prepared_monorepo(root: Path, *, run_id: str = RUN_ID, ignore_run_artifacts: bool = True) -> tuple[Path, Path, Path, dict]:
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
