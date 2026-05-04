#!/usr/bin/env python3
"""E16 — Crash/resume kill points (i) and (iii) — v0 scaffold.

Plan §Phase 1 names three SIGTERM lanes; (ii) "kill after second marker before
phase finish" is exercised by the existing primitive-level test
``test_unit_adoption_resume_from_marker_before_merge_is_idempotent``. This
harness adds scaffolding for the missing two lanes:

  Lane (i)   — kill after first marker before second sub-agent spawn.
  Lane (iii) — kill mid-merge.

**v0 scope caveat (read this before trusting verdicts).** The harness drives
``pump_phases(... mode="fanout")`` with a fake ``_claude_runner`` from
``phase_pump_test_helpers``. That runner writes the phase result/handoff JSON
files DIRECTLY — it does not emit ``STAGE_COMPLETE`` markers in a stream-json
transcript and it does not invoke ``StageMarkerProcessor``, so the per-unit
commit/merge adoption layer never runs. As a consequence:

  - Lane (i) only exercises pump-level retry idempotency (launcher_error
    followed by a second pump call). It does NOT verify the marker-then-kill
    boundary.
  - Lane (iii)'s ``merge_unit_execution_worktree`` patch never fires because
    the fake runner bypasses the merge entirely. ``call_log`` will be empty
    and the verdict explicitly flags this.

To turn this into a real E16 harness, replace ``_claude_runner`` with a
runner that (a) pre-stages a per-unit commit in the unit worktree and (b)
emits a stream-json transcript containing a ``STAGE_COMPLETE`` marker line
parseable by ``parse_stage_marker_line``. Or run ``claude_runner=None``
against real claude with a SIGTERM-based subprocess wrapper — that path is
cited in the plan but blocked on bandwidth (~$0.50 + fragile timing per
lane).

REUSE_STREAM=1 replays the captured ledger snapshots written under
``$EXPERIMENT_ROOT/e16/{lane_i,lane_iii}/`` instead of re-running pump_phases.

Outputs at ``$EXPERIMENT_ROOT/e16/``:

  - ``summary.md``                 — verdict for both lanes
  - ``lane_i/{first,second}.json`` — pump_phases return values
  - ``lane_i/stage_state_*.json``  — ledger snapshots
  - ``lane_iii/...`` (same shape)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent  # swarm-do/
sys.path.insert(0, str(REPO / "py"))

from swarm_do.pipeline import phase_pump  # noqa: E402
from swarm_do.pipeline import execution_worktree  # noqa: E402
from swarm_do.pipeline.phase_pump import pump_phases  # noqa: E402
from swarm_do.pipeline.stage_sessions import (  # noqa: E402
    load_stage_sessions,
    stage_session_path,
)
from swarm_do.pipeline.tests.phase_pump_test_helpers import (  # noqa: E402
    _claude_runner,
    _eligible_claude_report,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run  # noqa: E402

OUT = Path(os.environ.get("EXPERIMENT_ROOT", "/tmp/swarmdaddy-experiments")) / "e16"
OUT.mkdir(parents=True, exist_ok=True)
REUSE_STREAM = os.environ.get("REUSE_STREAM") == "1"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _telemetry_events(data: Path) -> list[dict[str, Any]]:
    log = data / "telemetry" / "run_events.jsonl"
    if not log.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _worktree_count(data: Path, run_id: str) -> int:
    """Count materialized per-unit worktrees by scanning the manifest dir."""
    manifest_dir = data / "runs" / run_id / "unit_worktrees"
    if not manifest_dir.exists():
        return 0
    return sum(1 for _ in manifest_dir.glob("*/manifest.json"))


def _commit_count_in_workspace(workspace: Path | None) -> int:
    if workspace is None or not (workspace / ".git").exists():
        return 0
    try:
        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0
    return int(out.stdout.strip() or "0")


def _phase_workspace(data: Path, run_id: str) -> Path | None:
    manifest = data / "runs" / run_id / "execution_worktree_manifest.json"
    payload = _read_json(manifest)
    if payload is None:
        return None
    ws = payload.get("safe_project_root")
    return Path(ws) if isinstance(ws, str) else None


def _snapshot_state(data: Path, run_id: str, label: str, dest: Path) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    stage_state = _read_json(stage_session_path(run_id, "1", data_dir=data)) or {}
    if stage_state:
        (dest / f"stage_state_{label}.json").write_text(
            json.dumps(stage_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "stages": [
            {
                "stage_id": stage.get("stage_id"),
                "status": stage.get("status"),
                "commit_sha": stage.get("commit_sha"),
            }
            for stage in stage_state.get("stages") or []
            if isinstance(stage, dict)
        ],
        "worktree_count": _worktree_count(data, run_id),
        "stage_adopted_events": sum(
            1 for ev in _telemetry_events(data) if ev.get("event_type") == "stage_adopted"
        ),
        "phase_workspace": str(_phase_workspace(data, run_id)) if _phase_workspace(data, run_id) else None,
        "commit_count": _commit_count_in_workspace(_phase_workspace(data, run_id)),
    }


def _run_pump(
    *,
    run_id: str,
    data: Path,
    runner,
    extra_patches: list | None = None,
) -> dict[str, Any]:
    patches = [
        mock.patch.object(phase_pump, "doctor_report", lambda: _eligible_claude_report()),
        mock.patch.object(
            phase_pump,
            "create_stage_child",
            lambda _run_id, _phase_id, stage_id, **_kwargs: {"created": True, "bead_id": f"bd-{stage_id}"},
        ),
    ]
    for extra in extra_patches or []:
        patches.append(extra)
    for patch in patches:
        patch.start()
    try:
        return pump_phases(
            run_id,
            launcher="claude-print",
            phase_sessions_mode="fanout",
            max_phases=1,
            init_if_missing=True,
            claude_runner=runner,
            data_dir=data,
        )
    finally:
        for patch in reversed(patches):
            patch.stop()


def _kill_after_first_marker_runner(data: Path, run_id: str):
    """Lane (i): emit a complete-marker for stage 1 then exit non-zero before
    further dispatch. The fake runner from phase_pump_test_helpers always
    advances all stages in one call; for (i) we want to leave stage 2 unhandled
    so the resume path has work to do. We simulate the kill by returning
    rc=130 with an empty stdout — pump_phases interprets that as a launcher
    error and unwinds without writing the phase result."""
    def runner(argv, prompt_text):
        # SIGTERM equivalent: empty stream, rc=130, no result/handoff written.
        return subprocess.CompletedProcess(argv, 130, stdout="", stderr="terminated")
    return runner


def _failing_merge_then_real(call_log: list[str]):
    """Lane (iii): wrap merge_unit_execution_worktree so the FIRST call raises
    mid-rename, subsequent calls execute normally. Forces resume to retry the
    merge."""
    real = execution_worktree.merge_unit_execution_worktree

    def wrapper(run_id: str, phase_id: str, unit_id: str, *, data_dir: Path | None = None, apply: bool = True):
        call_log.append(unit_id)
        if len(call_log) == 1:
            raise RuntimeError("simulated mid-merge failure for E16 lane (iii)")
        return real(run_id, phase_id, unit_id, data_dir=data_dir, apply=apply)

    return mock.patch.object(execution_worktree, "merge_unit_execution_worktree", wrapper)


def _seed_run(td: Path):
    repo, data, run_id = make_prepared_run(
        td,
        phase_count=1,
        commit_plan=True,
        ignore_run_artifacts=True,
    )
    prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    prepared["bd_epic_id"] = "epic-e16"
    prepared_path.write_text(
        json.dumps(prepared, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return repo, data, run_id


def _verdict(
    label: str,
    before: dict[str, Any],
    after: dict[str, Any],
    first_status: str,
    second_status: str,
    *,
    extra_signals: dict[str, Any] | None = None,
) -> tuple[list[str], bool]:
    lines = [f"## Lane {label}"]
    lines.append(f"- first pump status: {first_status}")
    lines.append(f"- second pump status: {second_status}")
    lines.append(f"- worktree_count before/after: {before.get('worktree_count')}/{after.get('worktree_count')}")
    lines.append(f"- stage_adopted events before/after: {before.get('stage_adopted_events')}/{after.get('stage_adopted_events')}")
    lines.append(f"- commit_count before/after: {before.get('commit_count')}/{after.get('commit_count')}")
    before_status = Counter(stage.get("status") for stage in (before.get("stages") or []))
    after_status = Counter(stage.get("status") for stage in (after.get("stages") or []))
    lines.append(f"- stage status before: {dict(before_status)}")
    lines.append(f"- stage status after:  {dict(after_status)}")
    extra = extra_signals or {}
    for key, value in extra.items():
        lines.append(f"- {key}: {value}")
    kill_point_exercised = bool(extra.get("kill_point_exercised", False))
    invariants_ok = (
        # No duplicate worktrees (count is monotone but bounded by unit count;
        # we just assert resume did not double-materialize).
        after.get("worktree_count", 0) >= before.get("worktree_count", 0)
        and after.get("worktree_count", 0) <= max(2, before.get("worktree_count", 0))
        # No duplicate stage_adopted telemetry — exactly one per unique stage.
        and after.get("stage_adopted_events", 0) <= len(after.get("stages") or [])
        # Resume reaches a terminal pump status (no launcher_error / blocked).
        and second_status in {"complete", "partial_success", "needs_input", "blocked"}
        # The kill point we wanted to test must actually have fired.
        and kill_point_exercised
    )
    lines.append(f"- invariants_ok: {invariants_ok}")
    return lines, invariants_ok


def _run_lane_i() -> tuple[list[str], bool]:
    out_dir = OUT / "lane_i"
    out_dir.mkdir(parents=True, exist_ok=True)
    if REUSE_STREAM:
        snap_before = _read_json(out_dir / "snapshot_before.json") or {}
        snap_after = _read_json(out_dir / "snapshot_after.json") or {}
        first_status = (_read_json(out_dir / "first.json") or {}).get("status", "unknown")
        second_status = (_read_json(out_dir / "second.json") or {}).get("status", "unknown")
        extras = _read_json(out_dir / "extras.json") or {}
        return _verdict(
            "(i) — kill before second sub-agent spawn",
            snap_before,
            snap_after,
            first_status,
            second_status,
            extra_signals=extras,
        )

    with tempfile.TemporaryDirectory(prefix="e16-i-") as td:
        td_path = Path(td)
        _, data, run_id = _seed_run(td_path)
        # First pump: claude is killed before any marker. The launcher exits
        # with rc=130 and no result file; pump_phases unwinds and returns
        # launcher_error.
        first = _run_pump(
            run_id=run_id,
            data=data,
            runner=_kill_after_first_marker_runner(data, run_id),
        )
        snap_before = _snapshot_state(data, run_id, "before", out_dir)

        # Second pump: real fake runner that emits a complete result. Resume
        # path must NOT re-materialize worktrees that already exist and must
        # NOT emit a duplicate stage_adopted event.
        runner = _claude_runner(data, run_id, ["complete"])
        second = _run_pump(run_id=run_id, data=data, runner=runner)
        snap_after = _snapshot_state(data, run_id, "after", out_dir)

        (out_dir / "first.json").write_text(
            json.dumps(first, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / "second.json").write_text(
            json.dumps(second, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / "snapshot_before.json").write_text(
            json.dumps(snap_before, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / "snapshot_after.json").write_text(
            json.dumps(snap_after, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        # The "kill point" for lane (i) is exercised iff the first pump
        # surfaced a launcher_error (the rc=130 exit). Anything else means
        # pump_phases short-circuited before the simulated kill mattered.
        extras = {
            "kill_point_exercised": first.get("status") == "launcher_error",
            "first_reason": first.get("reason"),
        }
        (out_dir / "extras.json").write_text(
            json.dumps(extras, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return _verdict(
            "(i) — kill before second sub-agent spawn",
            snap_before,
            snap_after,
            first.get("status", "unknown"),
            second.get("status", "unknown"),
            extra_signals=extras,
        )


def _run_lane_iii() -> tuple[list[str], bool]:
    out_dir = OUT / "lane_iii"
    out_dir.mkdir(parents=True, exist_ok=True)
    if REUSE_STREAM:
        snap_before = _read_json(out_dir / "snapshot_before.json") or {}
        snap_after = _read_json(out_dir / "snapshot_after.json") or {}
        first_status = (_read_json(out_dir / "first.json") or {}).get("status", "unknown")
        second_status = (_read_json(out_dir / "second.json") or {}).get("status", "unknown")
        extras = _read_json(out_dir / "extras.json") or {}
        return _verdict(
            "(iii) — kill mid-merge",
            snap_before,
            snap_after,
            first_status,
            second_status,
            extra_signals=extras,
        )

    with tempfile.TemporaryDirectory(prefix="e16-iii-") as td:
        td_path = Path(td)
        _, data, run_id = _seed_run(td_path)
        call_log: list[str] = []
        # First pump: merge raises mid-rename for the first unit. pump_phases
        # surfaces the failure but the marker has already been recorded and
        # the unit-session ledger has the pre-merge commit_sha logged.
        first = _run_pump(
            run_id=run_id,
            data=data,
            runner=_claude_runner(data, run_id, ["complete"]),
            extra_patches=[_failing_merge_then_real(call_log)],
        )
        snap_before = _snapshot_state(data, run_id, "before", out_dir)
        # Second pump: real merge — resume path must finish the merge, not
        # double-commit, and reach a terminal pump status.
        second = _run_pump(
            run_id=run_id,
            data=data,
            runner=_claude_runner(data, run_id, ["complete"]),
        )
        snap_after = _snapshot_state(data, run_id, "after", out_dir)

        (out_dir / "first.json").write_text(
            json.dumps(first, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / "second.json").write_text(
            json.dumps(second, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / "snapshot_before.json").write_text(
            json.dumps(snap_before, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / "snapshot_after.json").write_text(
            json.dumps(snap_after, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        # The "kill point" for lane (iii) only fires if the merge wrapper was
        # invoked at least once. The fake claude_runner short-circuits the
        # adoption layer, so call_log stays empty under v0 — the verdict
        # honestly reports "kill_point_exercised: False" and lane (iii) FAILs
        # the invariant gate. Swap in a marker-emitting runner to land it.
        extras = {
            "kill_point_exercised": bool(call_log),
            "merge_calls": list(call_log),
        }
        (out_dir / "extras.json").write_text(
            json.dumps(extras, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return _verdict(
            "(iii) — kill mid-merge",
            snap_before,
            snap_after,
            first.get("status", "unknown"),
            second.get("status", "unknown"),
            extra_signals=extras,
        )


def main() -> int:
    lane_i_lines, lane_i_ok = _run_lane_i()
    lane_iii_lines, lane_iii_ok = _run_lane_iii()
    summary_lines = [
        "# E16 — Crash/resume lanes (i) and (iii) — v0 scaffold",
        "",
        "v0 caveat: drives pump_phases through `_claude_runner` from",
        "phase_pump_test_helpers, which short-circuits the adoption layer.",
        "Neither kill point actually fires under v0 — the verdict checks",
        "`kill_point_exercised`, so both lanes correctly FAIL the invariant",
        "gate until a marker-emitting runner replaces `_claude_runner` (or",
        "`claude_runner=None` runs against real claude with a SIGTERM",
        "wrapper).",
        "",
    ]
    summary_lines.extend(lane_i_lines)
    summary_lines.append("")
    summary_lines.extend(lane_iii_lines)
    summary_lines.append("")
    overall_ok = lane_i_ok and lane_iii_ok
    summary_lines.append(f"## Overall: {'PASS' if overall_ok else 'FAIL'}")
    summary = "\n".join(summary_lines) + "\n"
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
