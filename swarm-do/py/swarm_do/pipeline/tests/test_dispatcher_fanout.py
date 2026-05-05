from __future__ import annotations

import json
import inspect
import dataclasses
import hashlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline import phase_pump
from swarm_do.pipeline.budget import DEFAULT_MAX_HANDOFFS, DEFAULT_MAX_WRITER_OUTPUT_BYTES, DEFAULT_MAX_WRITER_TOOL_CALLS
from swarm_do.pipeline.execution_worktree import materialize_run_execution_worktree, materialize_unit_execution_worktree
from swarm_do.pipeline.orchestrator_stream import count_malformed_stage_marker_candidates, parse_stage_marker_line, parse_stage_markers, parse_transcript_task_invocations
from swarm_do.pipeline.phase_pump import _dispatcher_fanout_permission_failure, pump_phases
from swarm_do.pipeline.phase_sessions import claim_next_phase, init_phase_sessions, phase_handoff_path, phase_result_path, start_phase
from swarm_do.pipeline.stage_controller import StageMarkerProcessor, resume_stage_adoption_journals, retry_failed_units
from swarm_do.pipeline.stage_invocation import _UNIT_WRITER_ROLES, plan_stage_invocations, render_orchestrator_brief, with_runtime_fields
from swarm_do.pipeline.stage_sessions import assign_stage_bead, init_stage_sessions, load_stage_sessions, record_stage_adopted, record_stage_retry_requested
from swarm_do.pipeline.tests.phase_pump_test_helpers import _claude_runner, _eligible_claude_report
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run
from swarm_do.pipeline.unit_session_adopter import _UNIT_MUTATING_ROLES
from swarm_do.pipeline.unit_sessions import load_unit_sessions


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class _MonkeyPatch:
    def __init__(self) -> None:
        self._undo: list[tuple[object, str, object]] = []

    def setattr(self, target: object, name: str, value: object) -> None:
        old_value = getattr(target, name)
        self._undo.append((target, name, old_value))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, old_value in reversed(self._undo):
            setattr(target, name, old_value)
        self._undo.clear()


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(value) and value.__module__ == __name__:
            suite.addTest(_function_test_case(value))
    return suite


def _function_test_case(func):
    def run() -> None:
        signature = inspect.signature(func)
        kwargs: dict[str, object] = {}
        temp_dirs: list[tempfile.TemporaryDirectory[str]] = []
        monkeypatch = None
        try:
            if "tmp_path" in signature.parameters:
                tmp = tempfile.TemporaryDirectory()
                temp_dirs.append(tmp)
                kwargs["tmp_path"] = Path(tmp.name)
            if "monkeypatch" in signature.parameters:
                monkeypatch = _MonkeyPatch()
                kwargs["monkeypatch"] = monkeypatch
            func(**kwargs)
        finally:
            if monkeypatch is not None:
                monkeypatch.undo()
            for tmp in reversed(temp_dirs):
                tmp.cleanup()

    return unittest.FunctionTestCase(run, description=func.__name__)


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


def test_malformed_stage_marker_candidate_is_counted_without_parsing() -> None:
    pretty_printed = 'STAGE_COMPLETE {"stage_id":"writer",\n"result_path":"/tmp/result.json"}'

    assert parse_stage_markers(pretty_printed) == []
    assert count_malformed_stage_marker_candidates(pretty_printed) == 1


def test_unit_writer_roles_match_unit_adopter_mutating_roles() -> None:
    assert _UNIT_WRITER_ROLES == _UNIT_MUTATING_ROLES == {"agent-writer"}


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
    assert "${MAX_TOOL_CALLS}" not in prompt
    assert "${MAX_OUTPUT_BYTES}" not in prompt
    assert "${MAX_HANDOFFS}" not in prompt
    assert "${WORK_UNIT_ID}" not in prompt
    assert f"max_writer_tool_calls={DEFAULT_MAX_WRITER_TOOL_CALLS}" in prompt
    assert f"max_writer_output_bytes={DEFAULT_MAX_WRITER_OUTPUT_BYTES}" in prompt
    assert f"max_handoffs={DEFAULT_MAX_HANDOFFS}" in prompt


def test_fanout_prompt_does_not_inline_writer_role_per_unit(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, [f"unit-{idx}" for idx in range(1, 7)])
    invocations, _snapshot = plan_stage_invocations(
        {"name": "default", "pipeline": "default"},
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
        prepared=prepared,
        phase_sessions_mode="fanout",
    )
    writers = [stage for stage in invocations if stage.agent_role == "agent-writer"]
    writers = with_runtime_fields(
        writers,
        worktree_paths={stage.work_unit_id or "": tmp_path / str(stage.work_unit_id or "unit") for stage in writers},
    )

    prompt = render_orchestrator_brief(
        base_prompt="# Base\n",
        stage_invocations=writers,
        run_id=RUN_ID,
        phase_id="1",
        phase_sessions_mode="fanout",
    )

    assert prompt.count("name: agent-writer") == 0
    assert len(prompt.encode("utf-8")) < 30_000


def test_readme_marker_documentation_does_not_parse_as_stage_markers() -> None:
    readme = (Path(__file__).resolve().parents[4] / "README.md").read_text(encoding="utf-8")

    assert parse_stage_markers(readme) == []


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
        )
        marker = _complete_marker(invocation)

        decision = processor.process_marker(marker)
        summary = processor.finish()
        state = load_stage_sessions(RUN_ID, "1", data_dir=data)

    assert decision.outcome == "blocked_recorded"
    assert not summary["completed"]
    assert state["stages"][0]["status"] == "blocked"
    assert state["stages"][0]["failure_kind"] == "blocked"


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


def test_structured_status_aliases_route_from_result_json() -> None:
    for status, outcome, ledger_status in [
        ("done", "adopted", "adopted"),
        ("done_with_concerns", "adopted_with_concerns", "adopted"),
        ("needs_context", "needs_input_recorded", "blocked"),
    ]:
        with tempfile.TemporaryDirectory() as td:
            data, invocation, processor = _processor(Path(td))
            _write_stage_result(invocation.expected_result_path, invocation, status=status, summary="alias")

            decision = processor.process_marker(_complete_marker(invocation))
            state = load_stage_sessions(RUN_ID, "1", data_dir=data)

        assert decision.outcome == outcome
        assert state["stages"][0]["status"] == ledger_status


def test_fanout_launch_contract_uses_bypass_and_agent_prompt(monkeypatch) -> None:
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

    try:
        plan_stage_invocations(
            {"name": "default", "pipeline": "default"},
            {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
            data_dir=data,
            prepared=prepared,
        )
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous multi-unit writer mapping was accepted")


def test_default_preset_auto_expands_writer_per_unit_in_fanout_mode(tmp_path: Path) -> None:
    """Decision 13's builder helper: in fanout mode the default preset
    (writer with no explicit ``fan_out``) auto-expands to one writer
    invocation per work unit. Downstream stages depending on ``writer``
    fan-in across all replicas via ``materialized_by_source``."""
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, ["unit-A", "unit-B", "unit-C"])

    invocations, _snapshot = plan_stage_invocations(
        {"name": "default", "pipeline": "default"},
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
        prepared=prepared,
        phase_sessions_mode="fanout",
    )

    writers = [stage for stage in invocations if stage.agent_role == "agent-writer"]
    assert [stage.stage_id for stage in writers] == [
        "writer:fanout-1",
        "writer:fanout-2",
        "writer:fanout-3",
    ]
    assert [stage.fan_out_index for stage in writers] == [0, 1, 2]
    assert [stage.work_unit_id for stage in writers] == ["unit-A", "unit-B", "unit-C"]

    spec_review = next(stage for stage in invocations if stage.agent_role == "agent-spec-review")
    assert list(spec_review.upstream_stage_ids) == [
        "writer:fanout-1",
        "writer:fanout-2",
        "writer:fanout-3",
    ]


def test_explicit_fan_out_preset_is_not_auto_expanded(tmp_path: Path) -> None:
    """An explicit ``fan_out`` declaration carries competitive-variant
    semantics (compete preset's two-model writer race), not
    one-replica-per-unit. Auto-expansion must NOT touch a stage that
    already declares ``fan_out`` even when N>1 work units are present —
    the preset author's count wins."""
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, ["unit-1", "unit-2", "unit-3"])
    preset = {
        "name": "compete-fixture",
        "pipeline_inline": {
            "pipeline_version": 1,
            "name": "compete-fixture",
            "stages": [
                {
                    "id": "writers",
                    "fan_out": {"role": "agent-writer", "count": 2, "variant": "models"},
                }
            ],
        },
    }

    invocations, _snapshot = plan_stage_invocations(
        preset,
        {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
        data_dir=data,
        prepared=prepared,
        phase_sessions_mode="fanout",
    )
    writers = [stage for stage in invocations if stage.agent_role == "agent-writer"]
    assert len(writers) == 2  # explicit count wins, NOT auto-expanded to 3
    assert [stage.fan_out_index for stage in writers] == [0, 1]


def test_auto_mode_unaffected_by_phase_sessions_mode_default(tmp_path: Path) -> None:
    """Backward-compat: legacy ``auto`` mode still raises the runtime
    ambiguity error. Decision 13 wants the rejection to move to preflight,
    but moving the gate is a separable change — this test pins the
    no-regression behaviour while that lands."""
    data = tmp_path / "data"
    data.mkdir()
    prepared = _prepared_with_units(tmp_path, ["unit-1", "unit-2"])
    try:
        plan_stage_invocations(
            {"name": "default", "pipeline": "default"},
            {"run_id": RUN_ID, "phase_id": "1", "phase_attempt": 1},
            data_dir=data,
            prepared=prepared,
            phase_sessions_mode="auto",
        )
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("auto mode unexpectedly accepted ambiguous multi-unit writer mapping")


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


def test_live_pump_two_unit_fanout_merges_both_units(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo, data, run_id = make_prepared_run(
            root,
            phase_count=1,
            commit_plan=True,
            ignore_run_artifacts=True,
        )
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        _replace_prepared_units(data, run_id, "1", ["unit-1", "unit-2"])
        seen: dict[str, object] = {}

        def runner(argv, prompt_text):
            contracts = _stage_contracts_from_dispatcher_prompt(prompt_text)
            seen["contracts"] = contracts
            markers: list[str] = []
            for contract in contracts:
                result_path = Path(str(contract["result_path"]))
                worktree_path = contract.get("worktree_path")
                if contract.get("agent_role") == "agent-writer" and isinstance(worktree_path, str):
                    allowed = [str(item) for item in contract.get("allowed_files") or [] if isinstance(item, str)]
                    rel = allowed[0] if allowed else f"docs/{contract['work_unit_id']}.md"
                    target = Path(worktree_path) / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"implemented {contract['work_unit_id']}\n", encoding="utf-8")
                payload = {
                    "schema_version": 1,
                    "run_id": contract["run_id"],
                    "phase_id": contract["phase_id"],
                    "phase_attempt": contract["phase_attempt"],
                    "stage_id": contract["stage_id"],
                    "result_path": str(result_path),
                    "work_unit_id": contract.get("work_unit_id"),
                    "worktree_path": contract.get("worktree_path"),
                    "bead_id": contract.get("bead_id"),
                    "allowed_files": list(contract.get("allowed_files") or []),
                    "status": "complete",
                    "summary": f"{contract['stage_id']} done",
                    "artifacts": [],
                }
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
                markers.append(
                    "STAGE_COMPLETE "
                    + json.dumps(
                        {
                            "stage_id": contract["stage_id"],
                            "result_path": str(result_path),
                            "summary": f"{contract['stage_id']} done",
                            "commit_subject": f"{contract['stage_id']} complete",
                        },
                        sort_keys=True,
                    )
                )
            return subprocess.CompletedProcess(argv, 0, stdout="\n".join(markers) + "\n", stderr="")

        monkeypatch.setattr(phase_pump, "doctor_report", lambda: _eligible_claude_report())
        monkeypatch.setattr(phase_pump, "run_phase_doctor", lambda *_args, **_kwargs: {"status": "ok", "findings": []})
        monkeypatch.setattr(phase_pump, "_resolve_phase_preset", lambda: _two_unit_writer_preset())

        result = pump_phases(
            run_id,
            launcher="claude-print",
            phase_sessions_mode="fanout",
            max_phases=1,
            init_if_missing=True,
            claude_runner=runner,
            data_dir=data,
        )

        command = json.loads(
            (data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "command.json").read_text(encoding="utf-8")
        )
        phase_result = json.loads(phase_result_path(run_id, "1", 1, data_dir=data).read_text(encoding="utf-8"))
        units = load_unit_sessions(run_id, data_dir=data)
        markers = command["stage_controller"]["markers"]
        integration_git = Path(markers[-1]["unit_adoption"]["merge"]["integration_git_worktree_root"])
        log = subprocess.run(
            ["git", "-C", str(integration_git), "log", "--format=%s"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.splitlines()

    assert result["status"] == "complete"
    assert [contract["work_unit_id"] for contract in seen["contracts"]] == ["unit-1", "unit-2"]
    assert command["stage_controller"]["completed_work_units"] == ["unit-1", "unit-2"]
    assert phase_result["merge_status"] == {"unit-1": "merged", "unit-2": "merged"}
    assert {unit["unit_id"]: unit["merge_state"] for unit in units["units"]} == {"unit-1": "merged", "unit-2": "merged"}
    assert "Merge work unit unit-1" in log
    assert "Merge work unit unit-2" in log


def test_dispatcher_prompt_overflow_records_structured_launcher_error(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _repo, data, run_id = make_prepared_run(root, phase_count=1, commit_plan=True, ignore_run_artifacts=True)
        init_phase_sessions(run_id, data_dir=data)
        claim = claim_next_phase(run_id, data_dir=data, lease_owner="owner-1")
        phase = start_phase(
            run_id,
            "1",
            launcher="claude-print",
            lease_owner=str(claim["lease_owner"]),
            data_dir=data,
        )["phase"]

        monkeypatch.setattr(phase_pump, "_resolve_phase_preset", lambda: {**_two_unit_writer_preset(), "budget": {"max_dispatcher_prompt_bytes": 1}})

        launch = phase_pump._run_claude_print_phase(
            run_id,
            "1",
            phase,
            lease_owner=str(claim["lease_owner"]),
            claude_runner=lambda _argv, _prompt: subprocess.CompletedProcess(_argv, 0, stdout="", stderr=""),
            claude_path="claude",
            max_budget_usd=None,
            phase_sessions_mode="fanout",
            data_dir=data,
        )

        command = json.loads((Path(str(launch["launch_dir"])) / "command.json").read_text(encoding="utf-8"))

    assert launch["status"] == "launcher_error"
    assert launch["reason"] == "dispatcher_prompt_too_large"
    assert command["reason"] == "dispatcher_prompt_too_large"
    assert command["dispatcher_prompt_budget"]["status"] == "fail"
    assert command["dispatcher_prompt_budget"]["max_dispatcher_prompt_bytes"] == 1
    assert command["dispatcher_prompt_budget"]["dispatcher_prompt_bytes"] > 1


def test_unit_stage_result_missing_identity_rejects_before_adoption() -> None:
    for missing_key in ["result_path", "work_unit_id", "worktree_path", "bead_id", "allowed_files"]:
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
            writer = dataclasses.replace(writer, bead_id="bd-writer")
            init_stage_sessions(run_id, "1", [writer], snapshot, data_dir=data)
            assign_stage_bead(run_id, "1", writer.stage_id, "bd-writer", data_dir=data)
            _write_stage_result(writer.expected_result_path, writer, run_id=run_id)
            payload = json.loads(writer.expected_result_path.read_text(encoding="utf-8"))
            payload.pop(missing_key)
            writer.expected_result_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
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

            decision = processor.process_marker(_complete_marker(writer))
            summary = processor.finish()
            state = load_stage_sessions(run_id, "1", data_dir=data)
            units = load_unit_sessions(run_id, data_dir=data)

        assert decision.outcome == "rejected_metadata_tampered"
        assert summary["rejected_metadata_tampered"] == 1
        assert state["stages"][0]["status"] == "blocked"
        assert units["units"][0]["merge_state"] == "pending"


def test_controller_phase_result_overwrites_stale_dispatcher_complete() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo, data, run_id = make_prepared_run(root, phase_count=1, commit_plan=True, ignore_run_artifacts=True)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
        phase = start_phase(run_id, "1", launcher="claude-print", lease_owner=str(claim["lease_owner"]), data_dir=data)["phase"]
        result_path = phase_result_path(run_id, "1", 1, data_dir=data)
        handoff_path = phase_handoff_path(run_id, "1", 1, data_dir=data)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text('{"status":"complete"}\n', encoding="utf-8")

        phase_pump._write_controller_phase_result(
            run_id,
            "1",
            phase,
            data_dir=data,
            result_path=result_path,
            handoff_path=handoff_path,
            stage_controller={
                "phase_result_status": "failed",
                "commits": [],
                "completed_work_units": [],
                "failed_work_units": ["unit-1"],
                "merge_status": {"unit-1": "failed"},
                "worktree_diff": None,
            },
            launcher="claude-print",
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))

    assert result["status"] == "failed"
    assert result["completed_work_units"] == []
    assert result["failed_work_units"] == ["unit-1"]
    assert result["merge_status"] == {"unit-1": "failed"}
    assert handoff["status"] == "failed"


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
        "result_path": str(path),
        "work_unit_id": invocation.work_unit_id,
        "worktree_path": str(invocation.worktree_path) if invocation.worktree_path else None,
        "bead_id": invocation.bead_id,
        "allowed_files": list(invocation.allowed_files),
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


def _two_unit_writer_preset() -> dict[str, object]:
    return {
        "name": "two-unit-writer-smoke",
        "pipeline_inline": {
            "pipeline_version": 1,
            "name": "two-unit-writer-smoke",
            "stages": [
                {"id": "writer", "agents": [{"role": "agent-writer"}]},
            ],
        },
        "budget": {},
    }


def _replace_prepared_units(data: Path, run_id: str, phase_id: str, unit_ids: list[str]) -> None:
    prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    descriptor = dict(prepared["work_unit_artifacts"][phase_id])
    artifact = dict(descriptor["artifact"])
    template = dict((artifact.get("work_units") or [{}])[0])
    artifact["work_units"] = [
        {
            **template,
            "id": unit_id,
            "title": unit_id,
            "goal": f"Implement {unit_id}",
            "allowed_files": [f"docs/{unit_id}.md"],
            "acceptance_criteria": [f"{unit_id} implemented"],
            "validation_commands": [],
        }
        for unit_id in unit_ids
    ]
    raw = (json.dumps(artifact, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sidecar_path = Path(str(prepared["repo_root"])) / str(descriptor["path"])
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_bytes(raw)
    descriptor["artifact"] = artifact
    descriptor["sha"] = hashlib.sha256(raw).hexdigest()
    prepared["work_unit_artifacts"][phase_id] = descriptor
    prepared_path.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stage_contracts_from_dispatcher_prompt(prompt_text: str) -> list[dict[str, object]]:
    contracts: list[dict[str, object]] = []
    for line in prompt_text.splitlines():
        if not line.startswith("Agent("):
            continue
        match = re.search(r", prompt=(.*)\)$", line)
        if match is None:
            continue
        agent_prompt = json.loads(match.group(1))
        contract_match = re.search(r"^Stage contract JSON: (\{.*\})$", agent_prompt, re.MULTILINE)
        if contract_match is None:
            continue
        payload = json.loads(contract_match.group(1))
        if isinstance(payload, dict):
            contracts.append(payload)
    return contracts
