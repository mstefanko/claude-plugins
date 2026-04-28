from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.cli import cmd_brainstorm, cmd_design, cmd_do, cmd_prepare, cmd_research, cmd_review
from swarm_do.pipeline.prepare import accept_prepared, load_prepared_artifact, prepare_plan_run
from swarm_do.pipeline.run_state import active_run_path, load_active_run


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class CommandProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        self.td = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.td.name

    def tearDown(self) -> None:
        self.td.cleanup()
        if self._old_data is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old_data

    def _dry_run(self, func, preset: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(preset=preset, target=[], dry_run=True)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = func(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def _accepted_prepared_run(self) -> tuple[Path, Path, str]:
        data = Path(self.td.name)
        repo = data / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True, env=env)
        (repo / "seed").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True, env=env)
        (repo / "README.md").write_text("# Test\n", encoding="utf-8")
        (repo / "plan.md").write_text(
            "### Phase 1: Docs (complexity: simple, kind: docs)\n\n"
            "### File Targets\n\n"
            "- `README.md`\n\n"
            "### Implementation\n\n"
            "- Update the README.\n\n"
            "### Acceptance Criteria\n\n"
            "- README is updated.\n\n"
            "### Validation Commands\n\n"
            "```\ntrue\n```\n",
            encoding="utf-8",
        )
        result = prepare_plan_run("plan.md", repo_root=repo, data_dir=data, run_id=RUN_ID)
        accept_prepared(RUN_ID, data_dir=data, repo_root=repo)
        assert result.artifact_path is not None
        return repo, data, result.artifact_path

    def test_output_profile_dry_runs_validate_matching_stock_presets(self) -> None:
        cases = (
            (cmd_brainstorm, "brainstorm"),
            (cmd_research, "research"),
            (cmd_research, "codebase-map"),
            (cmd_research, "research-orchestrator"),
            (cmd_design, "design"),
            (cmd_review, "review"),
            (cmd_review, "review-strict"),
        )

        for func, preset in cases:
            with self.subTest(preset=preset):
                code, stdout, stderr = self._dry_run(func, preset)

                self.assertEqual(code, 0, stderr)
                self.assertIn("Budget preview", stdout)
                self.assertIn("Stage graph", stdout)
                profile_name = {
                    "codebase-map": "research",
                    "research-orchestrator": "research",
                    "review-strict": "review",
                }.get(preset, preset)
                self.assertIn(f"{profile_name} preset {preset} is valid", stdout)

    def test_output_profile_rejects_wrong_preset_binding(self) -> None:
        code, _stdout, stderr = self._dry_run(cmd_design, "research")

        self.assertEqual(code, 1)
        self.assertIn("expected design", stderr)

    def test_prepare_profile_dry_run_does_not_dispatch_implementation(self) -> None:
        plan = "docs/swarmdaddy-prepare-gate-plan.md"
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            plan_path=plan,
            dry_run=True,
            auto_mechanical_fixes=False,
            accept=None,
            reject=None,
            accepted_by="human",
            reason="",
            json=True,
        )

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cmd_prepare(args)

        self.assertIn(code, {0, 1})
        self.assertEqual(stderr.getvalue(), "")
        payload = stdout.getvalue()
        self.assertIn('"run_id"', payload)
        self.assertIn('"status_label"', payload)
        self.assertFalse(os.path.exists(os.path.join(self.td.name, "runs")))

    def test_do_prepared_verifies_and_writes_active_run_without_decompose(self) -> None:
        _repo, data, _artifact_path = self._accepted_prepared_run()
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            target=None,
            prepared=RUN_ID,
            bd_epic_id="swarm-123",
            no_write_state=False,
            json=True,
        )

        with mock.patch(
            "swarm_do.pipeline.decompose.decompose_plan_phase",
            side_effect=AssertionError("dispatch must not decompose"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            code = cmd_do(args)

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ready_for_dispatch"])
        self.assertEqual(payload["run_id"], RUN_ID)
        state = load_active_run(active_run_path(data))
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "prepared")
        self.assertEqual(state["phase_id"], "prepared-dispatch")
        self.assertTrue(state["phase_map"])
        self.assertIn("review_findings", state)

    def test_do_prepared_accepts_artifact_path_form(self) -> None:
        _repo, _data, artifact_path = self._accepted_prepared_run()
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            target=artifact_path,
            prepared=True,
            bd_epic_id=None,
            no_write_state=True,
            json=True,
        )

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cmd_do(args)

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["run_id"], RUN_ID)

    def test_do_prepared_refuses_unaccepted_artifact_before_state_write(self) -> None:
        data = Path(self.td.name)
        repo = data / "repo-unaccepted"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True, env=env)
        (repo / "seed").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True, env=env)
        (repo / "plan.md").write_text(
            "### Phase 1: Docs (complexity: simple, kind: docs)\n\n"
            "### File Targets\n\n- `README.md`\n\n"
            "### Acceptance Criteria\n\n- README is updated.\n\n"
            "### Validation Commands\n\n```\ntrue\n```\n",
            encoding="utf-8",
        )
        prepare_plan_run("plan.md", repo_root=repo, data_dir=data, run_id=RUN_ID)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cmd_do(
                argparse.Namespace(
                    target=None,
                    prepared=RUN_ID,
                    bd_epic_id=None,
                    no_write_state=False,
                    json=True,
                )
            )

        self.assertEqual(code, 1)
        self.assertFalse(active_run_path(data).exists())
        self.assertIn("accepted", stderr.getvalue())

    def test_do_prepared_refuses_stale_work_unit_sidecar_before_state_write(self) -> None:
        repo, data, _artifact_path = self._accepted_prepared_run()
        loaded = load_prepared_artifact(RUN_ID, data_dir=data, repo_root=repo)
        first_descriptor = next(iter(loaded["work_unit_artifacts"].values()))
        (repo / first_descriptor["path"]).write_text('{"work_units": []}\n', encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cmd_do(
                argparse.Namespace(
                    target=None,
                    prepared=RUN_ID,
                    bd_epic_id=None,
                    no_write_state=False,
                    json=True,
                )
            )

        self.assertEqual(code, 1)
        self.assertFalse(active_run_path(data).exists())
        self.assertIn("sha mismatch", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
