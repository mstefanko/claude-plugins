from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from swarm_do.pipeline import phase_pump
from swarm_do.pipeline.execution_worktree import materialize_run_execution_worktree, materialize_unit_execution_worktree
from swarm_do.pipeline.orchestrator_stream import parse_stage_marker_line, parse_transcript_task_invocations
from swarm_do.pipeline.phase_pump import _dispatcher_fanout_permission_failure, pump_phases
from swarm_do.pipeline.stage_controller import StageMarkerProcessor, resume_stage_adoption_journals, retry_failed_units
from swarm_do.pipeline.stage_invocation import plan_stage_invocations, render_orchestrator_brief, with_runtime_fields
from swarm_do.pipeline.stage_sessions import init_stage_sessions, load_stage_sessions, record_stage_adopted, record_stage_retry_requested
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


def test_four_token_stage_markers_are_not_part_of_v1_contract() -> None:
    payload = json.dumps({"stage_id": "writer", "result_path": "/tmp/result.json"}, sort_keys=True)

    assert parse_stage_marker_line(f"STAGE_DONE_WITH_CONCERNS {payload}") is None
    assert parse_stage_marker_line(f"STAGE_NEEDS_CONTEXT {payload}") is None


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


def test_structured_status_needs_input_and_failed_route_through_result_json() -> None:
    with tempfile.TemporaryDirectory() as td:
        data, invocation, processor = _processor(Path(td))
        _write_stage_result(invocation.expected_result_path, invocation, status="needs_input", summary="need API token")

        needs_input = processor.process_marker(_complete_marker(invocation))
        state = load_stage_sessions(RUN_ID, "1", data_dir=data)

    assert needs_input.outcome == "needs_input_recorded"
    assert state["stages"][0]["status"] == "blocked"
    assert state["stages"][0]["failure_kind"] == "needs_input"

    with tempfile.TemporaryDirectory() as td:
        data, invocation, processor = _processor(Path(td))
        _write_stage_result(invocation.expected_result_path, invocation, status="failed", summary="bad output")

        failed = processor.process_marker(_complete_marker(invocation))
        state = load_stage_sessions(RUN_ID, "1", data_dir=data)

    assert failed.outcome == "failed_recorded"
    assert state["stages"][0]["status"] == "failed"
    assert state["stages"][0]["failure_kind"] == "failed"


@pytest.mark.parametrize(
    ("status", "outcome", "ledger_status"),
    [
        ("done", "adopted", "adopted"),
        ("done_with_concerns", "adopted_with_concerns", "adopted"),
        ("needs_context", "needs_input_recorded", "blocked"),
    ],
)
def test_structured_status_aliases_route_from_result_json(status: str, outcome: str, ledger_status: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        data, invocation, processor = _processor(Path(td))
        _write_stage_result(invocation.expected_result_path, invocation, status=status, summary="alias")

        decision = processor.process_marker(_complete_marker(invocation))
        state = load_stage_sessions(RUN_ID, "1", data_dir=data)

    assert decision.outcome == outcome
    assert state["stages"][0]["status"] == ledger_status


def test_fanout_launch_contract_uses_bypass_and_agent_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo, data, run_id = make_prepared_run(
            root,
            phase_count=1,
            commit_plan=True,
            ignore_run_artifacts=True,
        )
        prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        prepared["bd_epic_id"] = "epic-1"
        prepared_path.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        base_runner = _claude_runner(data, run_id, ["complete"])
        seen: dict[str, object] = {}

        def runner(argv, prompt_text):
            seen["argv"] = list(argv)
            seen["prompt"] = prompt_text
            stage_state = load_stage_sessions(run_id, "1", data_dir=data)
            seen["bead_ids_at_launch"] = [stage.get("bead_id") for stage in stage_state["stages"]]
            return base_runner(argv, prompt_text)

        monkeypatch.setattr(phase_pump, "doctor_report", lambda: _eligible_claude_report())
        monkeypatch.setattr(
            phase_pump,
            "create_stage_child",
            lambda _run_id, _phase_id, stage_id, **_kwargs: {"created": True, "bead_id": f"bd-{stage_id}"},
        )
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
    assert all(isinstance(item, str) and item.startswith("bd-") for item in seen["bead_ids_at_launch"])


def test_fanout_permission_contract_fails_without_bypass_or_agent_allowlist() -> None:
    assert (
        _dispatcher_fanout_permission_failure(
            ["claude", "-p", "--allowedTools", "Read", "Bash(git status:*)"],
            phase_sessions_mode="fanout",
        )
        == "dispatcher_missing_agent_tool"
    )
    assert _dispatcher_fanout_permission_failure(["claude", "-p", "--dangerously-skip-permissions"], phase_sessions_mode="fanout") is None
    assert _dispatcher_fanout_permission_failure(["claude", "-p", "--allowedTools", "Read", "Agent"], phase_sessions_mode="fanout") is None


def test_reduced_fanout_prompt_contains_only_retry_targets(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, ["unit-1", "unit-2"])
    preset = {
        "name": "fanout-test",
        "pipeline_inline": {
            "pipeline_version": 1,
            "name": "fanout-test",
            "stages": [
                {
                    "id": "writers",
                    "fan_out": {"role": "agent-writer", "count": 2, "variant": "same"},
                }
            ],
        },
    }
    invocations, snapshot = plan_stage_invocations(
        preset,
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
        prepared=prepared,
    )
    invocations = with_runtime_fields(
        invocations,
        worktree_paths={
            "unit-1": tmp_path / "unit-1",
            "unit-2": tmp_path / "unit-2",
        },
    )
    init_stage_sessions(RUN_ID, "1", invocations, snapshot, data_dir=data)
    record_stage_adopted(
        RUN_ID,
        "1",
        invocations[0].stage_id,
        commit_sha="a" * 40,
        result_path=invocations[0].expected_result_path,
        data_dir=data,
    )
    record_stage_retry_requested(
        RUN_ID,
        "1",
        invocations[1].stage_id,
        "RETRYABLE_TIMEOUT",
        "timeout",
        data_dir=data,
    )
    schedule = retry_failed_units(run_id=RUN_ID, phase_id="1", unit_ids=["unit-2"], data_dir=data)
    dispatch = phase_pump._stage_dispatch_metadata(RUN_ID, "1", invocations, phase_sessions_mode="fanout", data_dir=data)
    prompt = render_orchestrator_brief(
        base_prompt="# Base\n",
        stage_invocations=[stage for stage in invocations if stage.stage_id in dispatch["dispatch_stage_ids"]],
        run_id=RUN_ID,
        phase_id="1",
        phase_sessions_mode="fanout",
    )

    assert schedule["preserved_work_units"] == ["unit-1"]
    assert dispatch["preserved_work_units"] == ["unit-1"]
    assert dispatch["retry_target_work_units"] == ["unit-2"]
    assert "work_unit_id: unit-2" in prompt
    assert "work_unit_id: unit-1" not in prompt


def test_stage_invocation_mapping_for_multi_unit_writers_and_non_unit_stages(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, ["unit-1", "unit-2"])
    preset = {
        "name": "mapping-test",
        "pipeline_inline": {
            "pipeline_version": 1,
            "name": "mapping-test",
            "stages": [
                {
                    "id": "writers",
                    "fan_out": {"role": "agent-writer", "count": 2, "variant": "same"},
                    "merge": {"strategy": "synthesize", "agent": "agent-writer-judge"},
                },
                {
                    "id": "provider-review",
                    "depends_on": ["writers"],
                    "provider": {"type": "swarm-review"},
                },
            ],
        },
    }

    invocations, _snapshot = plan_stage_invocations(
        preset,
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
        prepared=prepared,
    )

    writers = [stage for stage in invocations if stage.agent_role == "agent-writer"]
    assert [stage.work_unit_id for stage in writers] == ["unit-1", "unit-2"]
    assert next(stage for stage in invocations if stage.merge_target == "writers").work_unit_id is None
    assert next(stage for stage in invocations if stage.is_provider_stage).work_unit_id is None


def test_ambiguous_multi_unit_writer_mapping_is_rejected(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, ["unit-1", "unit-2"])

    with pytest.raises(ValueError, match="ambiguous"):
        plan_stage_invocations(
            {"name": "default", "pipeline": "default"},
            {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
            data_dir=data,
            prepared=prepared,
        )


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


def test_unit_adoption_resume_from_marker_before_merge_is_idempotent() -> None:
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
        (unit_project / "docs" / "phase-1.md").write_text("resume adoption\n", encoding="utf-8")
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

        pending = processor.process_marker(marker)
        _write_stage_result(writer.expected_result_path, writer, run_id=run_id)
        first = resume_stage_adoption_journals(
            run_id=run_id,
            phase_id="1",
            phase_attempt=1,
            prepared=prepared,
            workspace_metadata={**run_worktree.to_metadata(), "phase_attempt": 1},
            launch_dir=data / "launch",
            data_dir=data,
            stage_invocations=[writer],
        )
        second = resume_stage_adoption_journals(
            run_id=run_id,
            phase_id="1",
            phase_attempt=1,
            prepared=prepared,
            workspace_metadata={**run_worktree.to_metadata(), "phase_attempt": 1},
            launch_dir=data / "launch",
            data_dir=data,
            stage_invocations=[writer],
        )
        units = load_unit_sessions(run_id, data_dir=data)
        events = [
            json.loads(line)
            for line in (data / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8").splitlines()
        ]

    assert pending.outcome == "pending"
    assert first["completed"]
    assert second["resumed_adoption_journals"] == []
    assert units["units"][0]["merge_state"] == "merged"
    assert first["markers"][0]["unit_adoption"]["status"] == "merged"
    assert sum(1 for event in events if event["event_type"] == "stage_adopted") == 1


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
    return _prepared_with_units(tmp_path, ["unit-1"])


def _prepared_with_units(tmp_path: Path, unit_ids: list[str]) -> dict:
    return {
        "repo_root": str(tmp_path),
        "work_unit_artifacts": {
            "1": {
                "artifact": {
                    "schema_version": 2,
                    "work_units": [
                        {
                            "id": unit_id,
                            "title": unit_id,
                            "goal": "Do it",
                            "allowed_files": [f"docs/{unit_id}.md"],
                            "acceptance_criteria": ["acceptance"],
                        }
                        for unit_id in unit_ids
                    ],
                },
                "path": "work_units.1.json",
                "sha": "0" * 64,
            }
        },
    }
