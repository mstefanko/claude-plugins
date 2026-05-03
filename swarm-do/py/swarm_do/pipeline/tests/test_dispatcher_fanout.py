from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from swarm_do.pipeline import phase_pump
from swarm_do.pipeline.execution_worktree import materialize_run_execution_worktree, materialize_unit_execution_worktree
from swarm_do.pipeline.orchestrator_stream import parse_stage_marker_line, parse_transcript_task_invocations
from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.stage_controller import StageMarkerProcessor
from swarm_do.pipeline.stage_invocation import plan_stage_invocations, render_orchestrator_brief, with_runtime_fields
from swarm_do.pipeline.stage_sessions import init_stage_sessions, load_stage_sessions
from swarm_do.pipeline.tests.phase_pump_test_helpers import _claude_runner, _eligible_claude_report
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run
from swarm_do.pipeline.unit_sessions import load_unit_sessions


pytestmark = pytest.mark.unit


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_tool_name_agent_alias(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    rows = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Agent", "input": {"description": "a"}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Task", "input": {"description": "b"}}]}},
    ]
    transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    invocations = parse_transcript_task_invocations(transcript)

    assert [item["description"] for item in invocations] == ["a", "b"]


def test_fanout_prompt_includes_agent_worktree_and_status_protocol(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    invocations, _snapshot = plan_stage_invocations(
        {"name": "default", "pipeline": "default"},
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
        prepared=_prepared_with_one_unit(tmp_path),
    )
    writer = next(stage for stage in invocations if stage.agent_role == "agent-writer")
    writer = with_runtime_fields(
        [writer],
        bead_ids={writer.stage_id: "bd-1"},
        worktree_paths={writer.work_unit_id or "": tmp_path / "unit" / "repo"},
    )[0]

    prompt = render_orchestrator_brief(
        base_prompt="# Base\n",
        stage_invocations=[writer],
        run_id=RUN_ID,
        phase_id="1",
        phase_sessions_mode="fanout",
    )

    assert "## Work Units To Dispatch" in prompt
    assert 'Agent(subagent_type="swarmdaddy:agent-writer"' in prompt
    assert "complete_with_concerns" in prompt
    assert f"cd {tmp_path / 'unit' / 'repo'} &&" in prompt
    assert "bead_id: bd-1" in prompt


def test_structured_status_complete_with_concerns_adopts() -> None:
    with tempfile.TemporaryDirectory() as td:
        data, invocation, processor = _processor(Path(td))
        _write_stage_result(invocation.expected_result_path, invocation, status="complete_with_concerns", summary="watch the edge")
        marker = _complete_marker(invocation)

        decision = processor.process_marker(marker)
        summary = processor.finish()
        state = load_stage_sessions(RUN_ID, "1", data_dir=data)

    assert decision.outcome == "adopted_with_concerns"
    assert summary["completed"]
    assert state["stages"][0]["status"] == "adopted"
    assert state["stages"][0]["notes"] == "watch the edge"


def test_structured_status_blocked_records_blocked_without_adoption() -> None:
    with tempfile.TemporaryDirectory() as td:
        data, invocation, processor = _processor(Path(td))
        _write_stage_result(
            invocation.expected_result_path,
            invocation,
            status="blocked",
            summary="blocked by missing spec",
            failure_kind="NON_RETRYABLE_INVALID_INPUT",
        )
        marker = _complete_marker(invocation)

        decision = processor.process_marker(marker)
        summary = processor.finish()
        state = load_stage_sessions(RUN_ID, "1", data_dir=data)

    assert decision.outcome == "blocked_recorded"
    assert not summary["completed"]
    assert state["stages"][0]["status"] == "blocked"
    assert state["stages"][0]["failure_kind"] == "NON_RETRYABLE_INVALID_INPUT"


def test_fanout_launch_contract_uses_bypass_and_agent_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo, data, run_id = make_prepared_run(
            root,
            phase_count=1,
            commit_plan=True,
            ignore_run_artifacts=True,
        )
        base_runner = _claude_runner(data, run_id, ["complete"])
        seen: dict[str, object] = {}

        def runner(argv, prompt_text):
            seen["argv"] = list(argv)
            seen["prompt"] = prompt_text
            return base_runner(argv, prompt_text)

        monkeypatch.setattr(phase_pump, "doctor_report", lambda: _eligible_claude_report())
        result = pump_phases(
            run_id,
            launcher="claude-print",
            phase_sessions_mode="fanout",
            max_phases=1,
            init_if_missing=True,
            claude_runner=runner,
            data_dir=data,
        )
        command = json.loads((data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "command.json").read_text(encoding="utf-8"))

    assert result["status"] == "complete"
    argv = seen["argv"]
    assert isinstance(argv, list)
    assert "--dangerously-skip-permissions" in argv
    assert "--allowedTools" not in argv
    assert command["phase_sessions_mode"] == "fanout"
    assert command["launch_contract"]["posture"] == "bypass-cascade"
    assert "Agent(subagent_type=" in str(seen["prompt"])
    assert "bash_cwd_discipline" in str(seen["prompt"])


def test_unit_marker_commits_unit_worktree_then_merges() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo, data, run_id = make_prepared_run(root, phase_count=1, commit_plan=True, ignore_run_artifacts=True)
        prepared = json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))
        run_worktree = materialize_run_execution_worktree(
            run_id,
            source_project_root=repo,
            data_dir=data,
            prepared_plan=prepared,
            sensitive_prefixes=[str(root / "home" / ".claude")],
        )
        invocations, snapshot = plan_stage_invocations(
            {"name": "default", "pipeline": "default"},
            {"run_id": run_id, "phase_id": "1", "phase_attempt": 1},
            data_dir=data,
            prepared=prepared,
        )
        writer = next(stage for stage in invocations if stage.agent_role == "agent-writer")
        assert writer.work_unit_id is not None
        unit_payload = materialize_unit_execution_worktree(run_id, "1", writer.work_unit_id, data_dir=data)
        writer = with_runtime_fields([writer], worktree_paths={writer.work_unit_id: unit_payload["project_root"]})[0]
        init_stage_sessions(run_id, "1", [writer], snapshot, data_dir=data)
        unit_project = Path(unit_payload["project_root"])
        (unit_project / "docs").mkdir(exist_ok=True)
        (unit_project / "docs" / "phase-1.md").write_text("unit adoption\n", encoding="utf-8")
        _write_stage_result(writer.expected_result_path, writer, run_id=run_id)
        marker = _complete_marker(writer)
        processor = StageMarkerProcessor(
            run_id=run_id,
            phase_id="1",
            phase_attempt=1,
            stage_invocations=[writer],
            prepared=prepared,
            workspace_metadata={**run_worktree.to_metadata(), "phase_attempt": 1},
            launch_dir=data / "launch",
            data_dir=data,
        )

        decision = processor.process_marker(marker)
        summary = processor.finish()
        state = load_stage_sessions(run_id, "1", data_dir=data)
        units = load_unit_sessions(run_id, data_dir=data)
        integration_project = Path(summary["markers"][0]["unit_adoption"]["merge"]["integration_project_root"])
        integration_content = (integration_project / "docs" / "phase-1.md").read_text(encoding="utf-8")

    assert decision.outcome == "adopted"
    assert summary["completed"]
    assert summary["completed_work_units"] == [writer.work_unit_id]
    assert state["stages"][0]["status"] == "adopted"
    assert units["units"][0]["merge_state"] == "merged"
    assert integration_content == "unit adoption\n"


def _processor(tmp: Path):
    data = tmp / "data"
    data.mkdir()
    invocations, snapshot = plan_stage_invocations(
        {"name": "default", "pipeline": "default"},
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
    )
    invocation = invocations[0]
    init_stage_sessions(RUN_ID, "1", [invocation], snapshot, data_dir=data)
    processor = StageMarkerProcessor(
        run_id=RUN_ID,
        phase_id="1",
        phase_attempt=1,
        stage_invocations=[invocation],
        prepared={},
        workspace_metadata={},
        launch_dir=tmp / "launch",
        data_dir=data,
    )
    return data, invocation, processor


def _complete_marker(invocation):
    marker = parse_stage_marker_line(
        "STAGE_COMPLETE "
        + json.dumps({"stage_id": invocation.stage_id, "result_path": str(invocation.expected_result_path)}, sort_keys=True)
    )
    assert marker is not None
    return marker


def _write_stage_result(
    path: Path,
    invocation,
    *,
    run_id: str = RUN_ID,
    status: str = "complete",
    summary: str = "done",
    failure_kind: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": "1",
        "phase_attempt": 1,
        "stage_id": invocation.stage_id,
        "status": status,
        "summary": summary,
        "artifacts": [],
    }
    if failure_kind:
        payload["failure_kind"] = failure_kind
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _prepared_with_one_unit(tmp_path: Path) -> dict:
    return {
        "repo_root": str(tmp_path),
        "work_unit_artifacts": {
            "1": {
                "artifact": {
                    "schema_version": 2,
                    "work_units": [
                        {
                            "id": "unit-1",
                            "title": "Unit 1",
                            "goal": "Do it",
                            "allowed_files": ["docs/phase-1.md"],
                            "acceptance_criteria": ["acceptance"],
                        }
                    ],
                },
                "path": "work_units.1.json",
                "sha": "0" * 64,
            }
        },
    }
