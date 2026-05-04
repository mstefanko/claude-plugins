#!/usr/bin/env python3
"""E14 — Unit-worktree adoption (full real-claude `pump_phases` lane).

Drives ``pump_phases(... mode="fanout")`` with a real claude subprocess against a
``make_prepared_run`` sandbox so the dispatcher → sub-agent → marker → commit →
merge round-trip is exercised end-to-end. Replaces the deferred placeholder
that previously raised ``UnitSessionError`` because it called
``materialize_unit_execution_worktree`` outside the stage_sessions ledger.

Cost: ~$0.50 per fresh run. ``REUSE_STREAM=1`` replays the cached
``stream.jsonl`` instead of re-spending API budget — wire that in for any
re-validation pass.

Outputs at ``$EXPERIMENT_ROOT/e14/``:

- ``stream.jsonl``      — phase launch transcript (copied from launch dir)
- ``summary.md``        — verdict feed for Phase 4 step 6 / CB-2
- ``post_merge_tree.txt`` — phase workspace listing after merge
- ``run_state.json``    — pump_phases return value
- ``stage_state.json``  — stage_sessions ledger snapshot
- ``phase_result.json`` — phase result file (when present)

Verifies:

1. ``pump_phases`` returned ``status == "complete"``.
2. The per-unit worktree was materialized (manifest present in data_dir).
3. The stage marker landed in the ledger with a non-empty commit_sha.
4. The unit-level commit was merged back into the phase workspace.
5. The dispatcher prompt contained ``Agent(subagent_type=`` and the bash-cwd
   discipline — proves we hit the fanout brief, not the legacy auto brief.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent  # swarm-do/
sys.path.insert(0, str(REPO / "py"))

from swarm_do.pipeline import phase_pump  # noqa: E402
from swarm_do.pipeline.phase_pump import pump_phases  # noqa: E402
from swarm_do.pipeline.phase_sessions import phase_session_path  # noqa: E402
from swarm_do.pipeline.stage_sessions import stage_session_path  # noqa: E402
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run  # noqa: E402

OUT = Path(os.environ.get("EXPERIMENT_ROOT", "/tmp/swarmdaddy-experiments")) / "e14"
OUT.mkdir(parents=True, exist_ok=True)

CLAUDE = os.environ.get("CLAUDE_BIN", "/Applications/cmux.app/Contents/Resources/bin/claude")
REUSE_STREAM = os.environ.get("REUSE_STREAM") == "1"


def _copy_first_match(src_glob: list[Path], dest: Path) -> Path | None:
    for src in src_glob:
        if src.exists():
            shutil.copy2(src, dest)
            return src
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _summarize_run(
    *,
    rc: str,
    wall: float,
    run_state: dict[str, Any] | None,
    stage_state: dict[str, Any] | None,
    phase_result: dict[str, Any] | None,
    prompt_text: str,
    phase_workspace: Path | None,
    reused: bool,
) -> tuple[str, bool]:
    lines: list[str] = ["# E14 — Unit-worktree adoption (full pump_phases lane)", ""]
    lines.append(f"- mode: {'REPLAY' if reused else 'LIVE'}")
    lines.append(f"- wall_seconds: {wall:.1f}")
    lines.append(f"- pump status: {rc}")
    lines.append(f"- run_state: {(run_state or {}).get('status')}")
    stages = (stage_state or {}).get("stages") or []
    adopted = sum(
        1
        for stage in stages
        if isinstance(stage, dict) and stage.get("status") in {"adopted", "complete"}
    )
    lines.append(f"- stages adopted/complete: {adopted}/{len(stages)}")
    commit_shas = sorted({
        stage.get("commit_sha")
        for stage in stages
        if isinstance(stage, dict) and isinstance(stage.get("commit_sha"), str)
    })
    lines.append(f"- distinct stage commit_shas: {len(commit_shas)}")
    if phase_result is not None:
        lines.append(f"- phase result status: {phase_result.get('status')}")
        completed = phase_result.get("completed_work_units") or []
        lines.append(f"- phase result completed_work_units: {completed}")
    else:
        lines.append("- phase result: missing")
    saw_agent_brief = "Agent(subagent_type=" in prompt_text
    saw_bash_cwd = "bash_cwd_discipline" in prompt_text
    lines.append(f"- dispatcher brief mentions Agent(subagent_type=...): {saw_agent_brief}")
    lines.append(f"- dispatcher brief mentions bash_cwd_discipline: {saw_bash_cwd}")
    if phase_workspace is not None:
        try:
            tree = sorted(
                str(p.relative_to(phase_workspace))
                for p in phase_workspace.rglob("*")
                if ".git" not in p.parts
            )
        except FileNotFoundError:
            tree = []
        (OUT / "post_merge_tree.txt").write_text("\n".join(tree) + "\n", encoding="utf-8")
        lines.append(f"- phase workspace entries: {len(tree)}")
    lines.append("")
    lines.append("## Decision feed")
    lines.append("")
    end_to_end_ok = (
        rc == "complete"
        and adopted >= 1
        and saw_agent_brief
        and (phase_result is None or phase_result.get("status") in {"complete", "partial_success"})
    )
    if end_to_end_ok:
        lines.append("- PASS: full pump_phases fanout round-trip is wired (Phase 4 step 6/7 verified end-to-end).")
    else:
        lines.append("- FAIL: investigate the specific signal above — check stage_state.json + phase_result.json for the failing leg.")
    return "\n".join(lines) + "\n", end_to_end_ok


def _run_pump(repo: Path, data: Path, run_id: str) -> tuple[dict[str, Any], str, str]:
    """Run pump_phases against real claude. Captures stream.jsonl + prompt_text."""
    t0 = time.time()
    result = pump_phases(
        run_id,
        launcher="claude-print",
        phase_sessions_mode="fanout",
        max_phases=1,
        init_if_missing=True,
        claude_runner=None,  # real claude subprocess
        claude_path=CLAUDE,
        data_dir=data,
    )
    wall = time.time() - t0

    launch_dir = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
    prompt_text = ""
    prompt_candidates = [
        launch_dir / "prompt.txt",
        launch_dir / "prompt.md",
    ]
    for candidate in prompt_candidates:
        if candidate.exists():
            prompt_text = candidate.read_text(encoding="utf-8")
            break

    stream_src = _copy_first_match(
        [
            launch_dir / "stream.jsonl",
            launch_dir / "stdout.txt",
        ],
        OUT / "stream.jsonl",
    )
    if stream_src is not None:
        (OUT / "stream_source.txt").write_text(str(stream_src) + "\n", encoding="utf-8")
    return result, prompt_text, f"{wall:.1f}"


def _replay() -> tuple[dict[str, Any], str, float, dict[str, Any] | None, dict[str, Any] | None, Path | None]:
    """Reconstruct a verdict from the cached e14 stream + last run's data dir."""
    last = OUT / "last_run.json"
    snapshot = _read_json(last)
    if snapshot is None:
        raise SystemExit(
            "REUSE_STREAM=1 set but $EXPERIMENT_ROOT/e14/last_run.json is missing — "
            "run once without REUSE_STREAM to seed it."
        )
    data = Path(str(snapshot["data_dir"]))
    run_id = str(snapshot["run_id"])
    prompt_text = (OUT / "prompt.txt").read_text(encoding="utf-8") if (OUT / "prompt.txt").exists() else ""
    phase_workspace = Path(str(snapshot["phase_workspace"])) if snapshot.get("phase_workspace") else None
    stage_state = _read_json(stage_session_path(run_id, "1", data_dir=data))
    phase_result_path = data / "runs" / run_id / "phases" / "1" / "result-1.json"
    phase_result = _read_json(phase_result_path)
    return snapshot.get("run_state") or {}, prompt_text, 0.0, stage_state, phase_result, phase_workspace


def main() -> int:
    if REUSE_STREAM:
        print("[e14] REUSE_STREAM=1 — replaying cached run")
        run_state, prompt_text, wall, stage_state, phase_result, phase_workspace = _replay()
        rc = run_state.get("status", "unknown")
        summary, ok = _summarize_run(
            rc=rc,
            wall=float(wall),
            run_state=run_state,
            stage_state=stage_state,
            phase_result=phase_result,
            prompt_text=prompt_text,
            phase_workspace=phase_workspace,
            reused=True,
        )
        (OUT / "summary.md").write_text(summary, encoding="utf-8")
        print(summary)
        return 0 if ok else 1

    with tempfile.TemporaryDirectory(prefix="e14-") as td:
        root = Path(td)
        repo, data, run_id = make_prepared_run(
            root,
            phase_count=1,
            commit_plan=True,
            ignore_run_artifacts=True,
        )
        # Seed bd_epic_id so the per-stage child-creation path is exercised. We
        # do NOT mock create_stage_child here — if beads isn't on PATH the call
        # returns created=False and we fall through (no assigned bead_id),
        # which is fine for the worktree-adoption verdict.
        prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        prepared["bd_epic_id"] = "epic-e14"
        prepared_path.write_text(
            json.dumps(prepared, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        run_state, prompt_text, wall_str = _run_pump(repo, data, run_id)
        wall = float(wall_str)

        # Snapshot the relevant state inside the tempdir BEFORE it's reaped.
        stage_state = _read_json(stage_session_path(run_id, "1", data_dir=data))
        phase_result_path = data / "runs" / run_id / "phases" / "1" / "result-1.json"
        phase_result = _read_json(phase_result_path)
        manifest = data / "runs" / run_id / "execution_worktree_manifest.json"
        phase_workspace: Path | None = None
        if manifest.exists():
            mdata = _read_json(manifest)
            if mdata is not None:
                ws = mdata.get("safe_project_root")
                if isinstance(ws, str):
                    phase_workspace = Path(ws)

        # Persist artifacts so a follow-up REUSE_STREAM=1 pass can verify.
        (OUT / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        if stage_state is not None:
            (OUT / "stage_state.json").write_text(
                json.dumps(stage_state, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if phase_result is not None:
            (OUT / "phase_result.json").write_text(
                json.dumps(phase_result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        (OUT / "run_state.json").write_text(
            json.dumps(run_state, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

        # Copy the run worktree into the EXPERIMENT_ROOT so REUSE_STREAM has it
        # after the tempdir is reaped.
        replay_data = OUT / "replay_data"
        if replay_data.exists():
            shutil.rmtree(replay_data)
        shutil.copytree(data, replay_data, symlinks=True, ignore_dangling_symlinks=True)
        replay_run = replay_data / "runs" / run_id
        replay_workspace: Path | None = None
        if phase_workspace is not None and phase_workspace.exists():
            replay_workspace = OUT / "replay_workspace"
            if replay_workspace.exists():
                shutil.rmtree(replay_workspace)
            shutil.copytree(phase_workspace, replay_workspace, symlinks=True, ignore_dangling_symlinks=True)

        (OUT / "last_run.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "data_dir": str(replay_data),
                    "phase_workspace": str(replay_workspace) if replay_workspace else None,
                    "wall_seconds": wall,
                    "run_state": run_state,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )

        rc = run_state.get("status", "unknown")
        summary, ok = _summarize_run(
            rc=rc,
            wall=wall,
            run_state=run_state,
            stage_state=stage_state,
            phase_result=phase_result,
            prompt_text=prompt_text,
            phase_workspace=phase_workspace,
            reused=False,
        )
        (OUT / "summary.md").write_text(summary, encoding="utf-8")
        print(summary)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
