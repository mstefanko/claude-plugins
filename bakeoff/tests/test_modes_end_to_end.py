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
    meta = json.loads((run_dir / "meta.json").read_text())
    report = (run_dir / "report.md").read_text()
    assert decision["decision_kind"] == "structured_union"
    assert meta["resolved_models"]["providers"]["claude"]["model"] == "fake-claude"
    assert meta["resolved_models"]["providers"]["codex"]["model"] == "fake-codex"
    assert meta["resolved_models"]["judge"]["model"] == "fake-judge"
    assert "Fake merged claim" in report


def test_triage_writes_structured_artifacts(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-run"]) == 0

    assert main(["triage", "triage-run", "--out", str(out_dir)]) == 0

    triage_dir = out_dir / "triage-run" / "triage"
    final = json.loads((triage_dir / "final.json").read_text())
    assert final["triage_participant"]["model"] == "fake-judge"
    assert final["items"] == []
    assert (triage_dir / "citation_checks.json").exists()


def test_triage_rejects_items_for_unselected_findings(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", triage_source_id="F-001")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-unselected"]) == 0

    assert main(["triage", "triage-unselected", "--out", str(out_dir)]) == 2

    triage_dir = out_dir / "triage-unselected" / "triage"
    status = json.loads((triage_dir / "status.json").read_text())
    assert status["status"] == "schema_error"
    assert "selected source_findings" in (triage_dir / "stderr.txt").read_text()


def test_triage_dry_run_and_force(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-dry"]) == 0

    assert main(["triage", "triage-dry", "--out", str(out_dir), "--dry-run"]) == 0

    triage_dir = out_dir / "triage-dry" / "triage"
    assert (triage_dir / "prompt.txt").exists()
    prompt = (triage_dir / "prompt.txt").read_text()
    assert '"source_finding_filter":' in prompt
    assert '"included": 0' in prompt
    assert '"skipped_non_actionable": 1' in prompt
    assert not (triage_dir / "final.json").exists()
    assert main(["triage", "triage-dry", "--out", str(out_dir)]) == 2
    assert main(["triage", "triage-dry", "--out", str(out_dir), "--force"]) == 0


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
    assert decision["spine_tiebreak"] == "position_a"
    assert "spine chosen by position_a after swap disagreement" in decision["caveats"][0]


def test_single_provider_only_mode_specific_caveat(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 0

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "single_provider_only"
    assert decision["judge_rationale"] == []
    assert "without dedupe" in decision["caveats"][0]


def test_format_retry_writes_provider_audit_artifacts(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", repair_providers={"codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "repair-run"]) == 0

    run_dir = out_dir / "repair-run"
    decision = json.loads((run_dir / "decision.json").read_text())
    codex_dir = run_dir / "providers" / "codex"
    codex_status = json.loads((codex_dir / "status.json").read_text())
    repair_status = json.loads((codex_dir / "repair-status.json").read_text())

    assert decision["decision_kind"] == "structured_union"
    assert decision["provider_statuses"]["codex"]["status"] == "ok_after_format_retry"
    assert codex_status["format_retry"]["initial_status"]["status"] == "schema_error"
    assert codex_status["format_retry"]["retry_status"]["status"] == "ok"
    assert repair_status["status"] == "ok"
    assert (codex_dir / "repair-prompt.txt").exists()
    assert (codex_dir / "repair-stdout.txt").exists()
    assert (codex_dir / "repair-stderr.txt").exists()
    assert (codex_dir / "final.json").exists()


def test_both_failed_exits_two(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"claude", "codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 2

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "both_failed"
    assert decision["judge_rationale"] == []


def install_fake_providers(
    tmp_path,
    *,
    judge_mode,
    fail_providers=frozenset(),
    repair_providers=frozenset(),
    triage_source_id=None,
):
    script = tmp_path / "fake_provider.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, os, pathlib, sys
            prompt = sys.stdin.read()
            name = os.environ.get("BAKEOFF_FAKE_PROVIDER_NAME", pathlib.Path(sys.argv[0]).name)
            fail_providers = {sorted(fail_providers)!r}
            repair_providers = {sorted(repair_providers)!r}
            judge_mode = {judge_mode!r}
            triage_source_id = {triage_source_id!r}
            compare_scores_a = {{"evidence":5,"coherence":5,"tradeoff_honesty":5,"rebuttals":5}}
            compare_scores_b = {{"evidence":4,"coherence":4,"tradeoff_honesty":4,"rebuttals":4}}
            analyze_scores_a = {{"step_atomicity":5,"citation_grounding":5,"assumption_transparency":5,"coherence":5}}
            analyze_scores_b = {{"step_atomicity":4,"citation_grounding":4,"assumption_transparency":4,"coherence":4}}

            def emit(obj):
                print("<scratchpad>ok</scratchpad>")
                print("<final_json>" + json.dumps(obj) + "</final_json>")

            if "--version" in sys.argv:
                print(name + " fake 1.0")
            elif name in fail_providers:
                print("provider failed before final json", file=sys.stderr)
                sys.exit(9)
            elif name in repair_providers and "BAKEOFF_FORMAT_RETRY_V1" not in prompt:
                emit({{"status":"complete","claims":[{{"id":"R-001","finding":name + " malformed claim"}}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}})
            elif "evidence-grounded triage of a Bakeoff report" in prompt:
                if triage_source_id is None:
                    emit({{"schema_version":1,"status":"complete","summary":"no selected findings","items":[],"unknowns":[]}})
                else:
                    emit({{"schema_version":1,"status":"complete","summary":"checked","items":[{{"id":"T-001","source_finding_id":triage_source_id,"source_finding":"Fake merged claim","classification":"real_issue","severity":"medium","confidence":"high","supporting_evidence":["src/fake.py:1"],"counterevidence":[],"citation_check_ids":[],"recommended_action":"fix_now","rationale":"actionable"}}],"unknowns":[]}})
            elif "deduplication and conflict-flagging judge" in prompt:
                emit({{"merged_claims":[{{"claim":"Fake merged claim","evidence":["fake:1"],"sources":["A","B"],"confidence":"high"}}],"conflicts":[],"unknowns_union":[]}})
            elif "pairwise judge" in prompt:
                winner = "B" if judge_mode == "compare_always_b" else "tie" if judge_mode == "compare_tie" else "A"
                emit({{"relation":"compare","scores_a":compare_scores_a,"scores_b":compare_scores_b,"winner":winner,"rationale":"position " + str(winner) + " looked better","kept_from_nonwinner":[{{"claim":"useful material from loser"}}],"consensus_strongest":[],"consensus_disagreements":[]}})
            elif "synthesis judge" in prompt:
                spine_winner = "B" if judge_mode == "analyze_always_b" else "A"
                emit({{"scores_a":analyze_scores_a,"scores_b":analyze_scores_b,"spine_winner":spine_winner,"spine_rationale":spine_winner + " is clearer","claim_verdicts":[],"additions_from_loser":[]}})
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
