import json
import os
import stat
import sys
import textwrap

from bakeoff.cli import main


def test_gather_research_with_fake_providers(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 0

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    report = (run_dir / "report.md").read_text()
    assert decision["decision_kind"] == "structured_union"
    assert "Fake merged claim" in report


def test_compare_position_swap_catches_position_bias(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="compare_always_a")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "compare")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 0

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "tie"


def test_analyze_selects_spine_with_tiebreak_audit(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="analyze_always_a")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "analyze")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 0

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "pick_winner"
    assert decision["spine_tiebreak"] in {"swap_agreement", "atomic_count", "position_a"}


def test_single_provider_only_mode_specific_caveat(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 0

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "single_provider_only"
    assert "without dedupe" in decision["caveats"][0]


def test_both_failed_exits_two(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"claude", "codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 2

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "both_failed"


def install_fake_providers(tmp_path, *, judge_mode, fail_providers=frozenset()):
    script = tmp_path / "fake_provider.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, os, pathlib, sys
            prompt = sys.stdin.read()
            name = os.environ.get("BAKEOFF_FAKE_PROVIDER_NAME", pathlib.Path(sys.argv[0]).name)
            fail_providers = {sorted(fail_providers)!r}

            def emit(obj):
                print("<scratchpad>ok</scratchpad>")
                print("<final_json>" + json.dumps(obj) + "</final_json>")

            if "--version" in sys.argv:
                print(name + " fake 1.0")
            elif name in fail_providers:
                print("provider failed before final json", file=sys.stderr)
                sys.exit(9)
            elif "deduplication and conflict-flagging judge" in prompt:
                emit({{"merged_claims":[{{"claim":"Fake merged claim","evidence":["fake:1"],"sources":["A","B"],"confidence":"high"}}],"conflicts":[],"unknowns_union":[]}})
            elif "pairwise judge" in prompt:
                emit({{"relation":"compare","scores_a":{{"evidence":5,"coherence":5,"tradeoff_honesty":5,"rebuttals":5}},"scores_b":{{"evidence":4,"coherence":4,"tradeoff_honesty":4,"rebuttals":4}},"winner":"A","rationale":"position A looked better","kept_from_nonwinner":[],"consensus_strongest":[],"consensus_disagreements":[]}})
            elif "synthesis judge" in prompt:
                emit({{"scores_a":{{}},"scores_b":{{}},"spine_winner":"A","spine_rationale":"A is clearer","claim_verdicts":[],"additions_from_loser":[]}})
            elif "comparison question" in prompt:
                emit({{"status":"complete","position":name + " position","claims":[{{"id":"R-001","claim":name + " claim","evidence":["fake:1"],"confidence":"high"}}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}})
            else:
                emit({{"status":"complete","claims":[{{"id":"R-001","claim":name + " claim","evidence":["fake:1"],"confidence":"high"}}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}})
            """
        ),
        encoding="utf-8",
    )
    for name in ("claude", "codex"):
        path = tmp_path / name
        path.write_text(
            f"#!/usr/bin/env sh\nBAKEOFF_FAKE_PROVIDER_NAME={name} exec {sys.executable} {script} \"$@\"\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def write_work_order(tmp_path, mode):
    scopes = ["codebase", "web"] if mode == "gather" else ["mixed", "mixed"]
    path = tmp_path / f"{mode}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": f"{mode}-fake",
                "type": mode,
                "goal": "Run fake bakeoff.",
                "background": "Fake context.",
                "providers": [
                    {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": scopes[0]},
                    {"id": "codex", "backend": "codex", "model": "fake-codex", "scope": scopes[1]},
                ],
                "judge": {"backend": "claude", "model": "fake-judge"},
                "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 20000},
            }
        ),
        encoding="utf-8",
    )
    return path
