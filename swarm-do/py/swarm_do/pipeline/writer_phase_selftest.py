"""Fast fake-launcher regression for phase-session stage quality."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

from .phase_pump import pump_phases
from .phase_sessions import init_phase_sessions, phase_status
from .stage_sessions import load_stage_sessions
from .tests.phase_session_fixtures import make_prepared_run


def run_writer_phase_selftest() -> dict[str, Any]:
    summary: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fake_home = root / "home"
        repo = fake_home / ".claude" / "plugins" / "swarm-do"
        repo, data, run_id = make_prepared_run(
            root,
            phase_count=1,
            repo_path=repo,
            commit_plan=True,
            ignore_run_artifacts=True,
        )
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        with mock.patch("swarm_do.pipeline.execution_workspace.Path.home", return_value=fake_home):
            result = pump_phases(
                run_id,
                launcher="fake-test",
                max_phases=1,
                data_dir=data,
                synthetic_writes=[
                    {
                        "path": "docs/phase-1.md",
                        "content": "phase one note\n",
                    }
                ],
                synthetic_task_dispatches=[
                    {"subagent_type": "general-purpose", "prompt": "research"},
                    {"subagent_type": "general-purpose", "prompt": "writer"},
                    {"subagent_type": "general-purpose", "prompt": "docs"},
                ],
            )
        status = phase_status(run_id, data_dir=data, repo_root=repo)
        stage_state = load_stage_sessions(run_id, "1", data_dir=data)
        writer_stage = next(stage for stage in stage_state["stages"] if stage["stage_id"] == "writer")
        result_path = Path(status["phases"][0]["result_path"])
        phase_result = json.loads(result_path.read_text(encoding="utf-8"))
        checks = {
            "phase_complete": result.get("status") in {"complete", "max_phases"} and status.get("status") == "complete",
            "all_stages_adopted": all(stage.get("status") == "adopted" for stage in stage_state["stages"]),
            "writer_stage_adopted": writer_stage.get("status") == "adopted",
            "writer_commit": isinstance(writer_stage.get("commit_sha"), str) and bool(writer_stage.get("commit_sha")),
            "committed_diff": "docs/phase-1.md" in phase_result.get("worktree_diff", {}).get("committed", []),
            "run_artifacts_excluded": not any(
                "data/runs/" in path
                for values in phase_result.get("worktree_diff", {}).values()
                if isinstance(values, list)
                for path in values
            ),
        }
        for name, passed in checks.items():
            summary.append(f"{name}: {'pass' if passed else 'fail'}")
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "run_id": run_id,
            "summary": summary,
            "checks": checks,
            "stage_session_path": str(data / "runs" / run_id / "phases" / "1" / "stage_sessions.v1.json"),
        }


__all__ = ["run_writer_phase_selftest"]
