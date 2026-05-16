import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import textwrap

from bakeoff import cli as cli_module
from bakeoff.cli import main
from bakeoff.manifest import write_run_manifest
from bakeoff.review_context import ReviewContext
from bakeoff.work_order import ValidationError, strip_jsonc_comments


def test_init_review_writes_gather_recipe(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["init", "review"]) == 0

    output = capsys.readouterr().out
    data = json.loads(strip_jsonc_comments((tmp_path / "review.work-order.json").read_text()))
    assert "recipe: review (mode gather)" in output
    assert data["type"] == "gather"
    assert data["facet"]["id"] == "code-review"


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
    assert meta["scope_policy"] == {"enforcement": "best_effort"}
    assert meta["resolved_models"]["providers"]["claude"]["scope_enforcement"]["requested_scope"] == "codebase"
    assert meta["resolved_models"]["providers"]["codex"]["scope_enforcement"]["effective_scope"] == "web"
    assert meta["resolved_models"]["providers"]["codex"]["scope_enforcement"]["temporary_cwd"] is True
    assert not Path(meta["resolved_models"]["providers"]["codex"]["scope_enforcement"]["cwd"]).exists()
    assert meta["resolved_models"]["judge"]["model"] == "fake-judge"
    assert "Fake merged claim" in report


def test_code_review_facet_auto_triages_successful_research(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "review-run"]) == 0

    run_dir = out_dir / "review-run"
    meta = json.loads((run_dir / "meta.json").read_text())
    report = (run_dir / "report.md").read_text()
    triage_dir = run_dir / "triage"
    triage_prompt = (triage_dir / "prompt.txt").read_text()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert meta["facet"]["id"] == "code-review"
    assert "Facet: `code-review`" in report
    assert (triage_dir / "final.json").exists()
    assert manifest["triage"]["state"] == "yes"
    assert manifest["triage"]["attempt_status"] in {"ok", "ok_after_format_retry"}
    assert '"facet": {' in triage_prompt
    assert '"id": "code-review"' in triage_prompt

    assert main(["show", "review-run", "--out", str(out_dir)]) == 0
    show_output = capsys.readouterr().out
    assert "triage available: bakeoff show review-run --triage" in show_output
    assert f"--out {out_dir}" in show_output
    assert "triage not yet run" not in show_output

    assert main(["ls", "--out", str(out_dir)]) == 0
    ls_output = capsys.readouterr().out
    assert "run_id\ttype\tfacet\tdecision\ttriage\tfinished_at" in ls_output
    assert "review-run\tgather\tcode-review\tstructured_union\ttriage:yes\t" in ls_output


def test_code_review_facet_can_skip_auto_triage(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "review-skip", "--no-triage"]) == 0

    output = capsys.readouterr().out
    assert "recommended: bakeoff triage review-skip" not in output
    assert "auto-triage" not in output
    assert not (out_dir / "review-skip" / "triage").exists()


def test_research_base_diff_writes_review_context_and_manifest(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"

    assert (
        main(
            [
                "research",
                str(work_order),
                "--out",
                str(out_dir),
                "--run-id",
                "review-context-run",
                "--base",
                "main",
                "--diff",
                "--no-triage",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    run_dir = out_dir / "review-context-run"
    effective = json.loads((run_dir / "work-order.json").read_text())
    source = json.loads((run_dir / "source-work-order.json").read_text())
    context_json = json.loads((run_dir / "review-context.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())

    assert "review context: base main" in output
    assert f"context-md: {run_dir / 'review-context.md'}" in output
    assert f"manifest: {run_dir / 'manifest.json'}" in output
    assert "<generated_review_context>" in effective["background"]
    assert "diff --git" in effective["background"]
    assert "<generated_review_context>" not in source["background"]
    assert context_json["base_ref"] == "main"
    assert context_json["included_sections"] == ["metadata", "diffstat", "changed_files", "patch"]
    assert context_json["sections"]["patch"]["text"].startswith("diff --git")
    assert manifest["review_context"]["present"] is True
    assert manifest["review_context"]["base_ref"] == "main"
    assert manifest["artifacts"]["source_work_order"] == "source-work-order.json"
    assert manifest["artifacts"]["review_context_md"] == "review-context.md"
    assert manifest["artifact_fingerprints"]["review-context.json"]["size_bytes"] > 0
    assert "providers/claude/stdout.txt" not in manifest["artifact_fingerprints"]
    assert manifest["providers"]["claude"]["status"] == "ok"
    assert manifest["triage"]["state"] == "no"


def test_rerun_copies_review_context_without_recapturing_git(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"
    assert (
        main(
            [
                "research",
                str(work_order),
                "--out",
                str(out_dir),
                "--run-id",
                "source-review",
                "--base",
                "main",
                "--diff",
                "--no-triage",
            ]
        )
        == 0
    )
    source_context = (out_dir / "source-review" / "review-context.md").read_text()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("rerun should not regenerate review context")

    monkeypatch.setattr(cli_module, "build_review_context", fail_if_called)

    assert main(["rerun", "source-review", "--out", str(out_dir), "--run-id", "replayed-review", "--no-triage"]) == 0

    replay_dir = out_dir / "replayed-review"
    assert (replay_dir / "source-work-order.json").exists()
    assert (replay_dir / "review-context.json").exists()
    assert (replay_dir / "review-context.md").read_text() == source_context
    manifest = json.loads((replay_dir / "manifest.json").read_text())
    assert manifest["review_context"]["present"] is True
    assert manifest["artifacts"]["review_context_json"] == "review-context.json"


def test_review_context_failure_preserves_existing_run_dir(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    existing = out_dir / "blocked"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("old run\n", encoding="utf-8")

    def fail_context(*args, **kwargs):
        raise ValidationError("review context patch is 120001 bytes, exceeding 120000 bytes")

    monkeypatch.setattr(cli_module, "build_review_context", fail_context)

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "blocked", "--force", "--diff"]) == 2

    assert (existing / "keep.txt").read_text(encoding="utf-8") == "old run\n"
    assert not (existing / "work-order.json").exists()


def test_review_context_for_non_code_review_facet_prints_note(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"

    def fake_context(options, cwd, started_at):
        return ReviewContext(
            generated_at=started_at,
            base_ref="HEAD",
            base_commit="abc123",
            head_ref="main",
            head_commit="abc123",
            worktree_dirty=False,
            git_root=str(tmp_path),
            capture_cwd=str(tmp_path),
            pathspec=".",
            included_sections=["metadata", "diffstat", "changed_files"],
            diffstat="",
            changed_files="",
            patch=None,
        )

    monkeypatch.setattr(cli_module, "build_review_context", fake_context)

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "plain-context", "--changed-files"]) == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "note: generated review context was requested for a non-code-review facet" in captured.err
    assert "review context: base HEAD abc123" in output
    assert f"context-md: {out_dir / 'plain-context' / 'review-context.md'}" in output


def test_rerun_can_skip_code_review_auto_triage(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "review-source"]) == 0
    capsys.readouterr()

    assert main(["rerun", "review-source", "--out", str(out_dir), "--run-id", "review-rerun", "--no-triage"]) == 0

    output = capsys.readouterr().out
    assert "recommended: bakeoff triage review-rerun" not in output
    assert "auto-triage" not in output
    assert not (out_dir / "review-rerun" / "triage").exists()


def test_code_review_facet_does_not_auto_triage_single_provider_run(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "review-partial"]) == 0

    output = capsys.readouterr().out
    assert "auto-triage:" not in output
    assert "recommended: bakeoff triage review-partial" in output
    assert not (out_dir / "review-partial" / "triage").exists()


def test_show_labels_stale_triage(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "review-stale"]) == 0
    capsys.readouterr()

    report_path = out_dir / "review-stale" / "report.md"
    report_path.write_text(report_path.read_text() + "\nchanged after triage\n", encoding="utf-8")

    assert main(["show", "review-stale", "--out", str(out_dir)]) == 0

    output = capsys.readouterr().out
    assert "triage stale (report.md changed): bakeoff triage review-stale --force" in output
    assert f"--out {out_dir}" in output
    assert "triage not yet run" not in output

    assert main(["show", "review-stale", "--out", str(out_dir), "--triage"]) == 2
    error = capsys.readouterr().err
    assert "triage is stale for review-stale (report.md changed)" in error
    assert "bakeoff triage review-stale --force" in error
    assert f"--out {out_dir}" in error

    assert main(["ls", "--out", str(out_dir)]) == 0
    ls_output = capsys.readouterr().out
    assert "review-stale\tgather\tcode-review\tstructured_union\ttriage:stale\t" in ls_output


def test_show_recommendation_uses_current_work_order_facet(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "review-current", "--no-triage"]) == 0
    capsys.readouterr()

    run_work_order_path = out_dir / "review-current" / "work-order.json"
    run_work_order = json.loads(run_work_order_path.read_text())
    run_work_order["facet"]["id"] = "security"
    run_work_order_path.write_text(json.dumps(run_work_order), encoding="utf-8")

    assert main(["show", "review-current", "--out", str(out_dir)]) == 0

    output = capsys.readouterr().out
    assert "triage not yet run" not in output


def test_no_triage_is_noop_for_non_code_review_facet(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "security"})
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "security-run", "--no-triage"]) == 0

    assert not (out_dir / "security-run" / "triage").exists()


def test_triage_writes_structured_artifacts(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-run"]) == 0
    capsys.readouterr()

    assert main(["triage", "triage-run", "--out", str(out_dir)]) == 0
    output = capsys.readouterr().out
    assert "source findings: selected 0; skipped 1 non-actionable; skipped 0 out-of-facet" in output
    assert f"source filter: {out_dir / 'triage-run' / 'triage' / 'source_finding_filter.json'}" in output
    assert f"next:   bakeoff show triage-run --triage --out {out_dir}" in output

    triage_dir = out_dir / "triage-run" / "triage"
    final = json.loads((triage_dir / "final.json").read_text())
    assert final["triage_participant"]["model"] == "fake-judge"
    assert final["source_finding_filter"] == {
        "included": 0,
        "skipped_non_actionable": 1,
        "skipped_out_of_facet": 0,
    }
    assert final["items"] == []
    assert (triage_dir / "citation_checks.json").exists()
    source_filter_artifact = json.loads((triage_dir / "source_finding_filter.json").read_text())
    assert source_filter_artifact["summary"] == final["source_finding_filter"]
    assert source_filter_artifact["selected"] == []
    assert source_filter_artifact["skipped"][0]["skip_reason"] == "non_actionable"
    triage_report = (triage_dir / "triage.md").read_text()
    assert "## Source Findings" in triage_report
    assert "- Selected: `0`" in triage_report
    assert "- Skipped non-actionable: `1`" in triage_report
    assert "- Skipped out-of-facet: `0`" in triage_report


def test_triage_rejects_items_for_unselected_findings(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", triage_source_id="F-001")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-unselected"]) == 0

    assert main(["triage", "triage-unselected", "--out", str(out_dir)]) == 1

    triage_dir = out_dir / "triage-unselected" / "triage"
    status = json.loads((triage_dir / "status.json").read_text())
    assert status["status"] == "schema_error"
    assert "selected source_findings" in (triage_dir / "stderr.txt").read_text()


def test_triage_dry_run_and_force(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-dry"]) == 0

    assert main(["triage", "triage-dry", "--out", str(out_dir), "--dry-run"]) == 0
    output = capsys.readouterr().out

    triage_dir = out_dir / "triage-dry" / "triage"
    status = json.loads((triage_dir / "status.json").read_text())
    assert status["source_finding_filter"] == {
        "included": 0,
        "skipped_non_actionable": 1,
        "skipped_out_of_facet": 0,
    }
    assert (triage_dir / "prompt.txt").exists()
    prompt = (triage_dir / "prompt.txt").read_text()
    assert '"source_finding_filter":' in prompt
    assert '"included": 0' in prompt
    assert '"skipped_non_actionable": 1' in prompt
    assert '"skipped_out_of_facet": 0' in prompt
    assert not (triage_dir / "final.json").exists()
    assert f"source filter: {triage_dir / 'source_finding_filter.json'}" in output
    assert f"triage dry run: {triage_dir / 'prompt.txt'}" in output
    assert f"triage status:  {triage_dir / 'status.json'}" in output
    assert f"next:           bakeoff triage triage-dry --force --out {out_dir}" in output

    assert main(["ls", "--out", str(out_dir)]) == 0
    ls_output = capsys.readouterr().out
    assert "run_id\ttype\tfacet\tdecision\ttriage\tfinished_at" in ls_output
    assert "triage-dry\tgather\t-\tstructured_union\ttriage:dry_run\t" in ls_output

    assert main(["triage", "triage-dry", "--out", str(out_dir)]) == 2
    error = capsys.readouterr().err
    assert f"bakeoff triage triage-dry --force --out {out_dir}" in error
    assert main(["triage", "triage-dry", "--out", str(out_dir), "--force"]) == 0


def test_ls_reports_empty_out_dir(tmp_path, capsys):
    out_dir = tmp_path / "missing-runs"

    assert main(["ls", "--out", str(out_dir)]) == 0

    assert f"no runs found under {out_dir}" in capsys.readouterr().out


def test_ls_json_scans_manifests_and_legacy_runs_with_filters(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "manifest-run", "--no-triage"]) == 0
    capsys.readouterr()

    legacy_dir = out_dir / "legacy-run"
    legacy_dir.mkdir()
    (legacy_dir / "work-order.json").write_text("{}\n", encoding="utf-8")
    (legacy_dir / "report.md").write_text("# legacy\n", encoding="utf-8")
    (legacy_dir / "decision.json").write_text(
        json.dumps({"decision_kind": "structured_union", "judge_ran": True}) + "\n",
        encoding="utf-8",
    )
    (legacy_dir / "meta.json").write_text(
        json.dumps(
            {
                "type": "gather",
                "facet": {"id": "code-review"},
                "finished_at": "2026-05-16T12:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["ls", "--out", str(out_dir), "--json", "--facet", "code-review", "--triage-state", "no"]) == 0

    payload = json.loads(capsys.readouterr().out)
    rows_by_id = {row["run_id"]: row for row in payload["runs"]}
    assert rows_by_id["manifest-run"]["manifest_state"] == "present"
    assert rows_by_id["manifest-run"]["manifest_path"] == str(out_dir / "manifest-run" / "manifest.json")
    assert rows_by_id["legacy-run"]["manifest_state"] == "missing"
    assert "manifest_path" not in rows_by_id["legacy-run"]


def test_show_judge_artifacts_empty_state_names_decision(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "single-provider"]) == 0
    capsys.readouterr()

    assert main(["show", "single-provider", "--out", str(out_dir), "--judge"]) == 0

    output = capsys.readouterr().out
    assert "no judge result artifacts for single-provider" in output
    assert "decision: single_provider_only" in output
    assert "judge_ran: false" in output


def test_compare_position_swap_catches_position_bias(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="compare_always_a")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "compare")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 3

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    report = (run_dir / "report.md").read_text()
    assert decision["decision_kind"] == "tie"
    assert "Judge passes:" in report
    assert "pass2: A=`codex`, B=`claude`" in report


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


def test_both_failed_exits_one(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"claude", "codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")

    assert main(["research", str(work_order), "--out", str(tmp_path / "runs")]) == 1

    run_dir = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "both_failed"
    assert decision["judge_rationale"] == []


def test_judge_runtime_failure_exits_one(tmp_path, monkeypatch):
    install_fake_providers(tmp_path, judge_mode="gather", fail_judge=True)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "judge-failed"]) == 1

    run_dir = out_dir / "judge-failed"
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["decision_kind"] == "structured_union"
    assert decision["caveats"] == ["gather judge failed with exit_error"]


def test_research_json_success_emits_single_summary(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "json-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "research"
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["run_id"] == "json-run"
    assert payload["decision_kind"] == "structured_union"
    assert payload["providers"]["claude"]["status"] == "ok"
    assert payload["triage"]["auto_started"] is False
    assert "bakeoff research" not in captured.out
    assert "[claude]" not in captured.err


def test_research_json_both_failed_and_compare_tie_exit_codes(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather", fail_providers={"claude", "codex"})
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    failed_work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"

    assert main(["research", str(failed_work_order), "--out", str(out_dir), "--run-id", "failed-json", "--json"]) == 1
    failed_payload = json.loads(capsys.readouterr().out)
    assert failed_payload["status"] == "failed"
    assert failed_payload["decision_kind"] == "both_failed"
    assert failed_payload["providers"]["claude"]["status"] == "failed"

    install_fake_providers(tmp_path, judge_mode="compare_always_a")
    compare_work_order = write_work_order(tmp_path, "compare")

    assert main(["research", str(compare_work_order), "--out", str(out_dir), "--run-id", "tie-json", "--json"]) == 3
    tie_payload = json.loads(capsys.readouterr().out)
    assert tie_payload["status"] == "judge_disagreement"
    assert tie_payload["decision_kind"] == "tie"
    assert tie_payload["exit_code"] == 3


def test_research_json_auto_triage_summary(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "auto-json", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["triage"]["auto_started"] is True
    assert payload["triage"]["state"] == "yes"
    assert payload["triage"]["exit_code"] == 0
    assert "final" in payload["triage"]["artifacts"]
    assert "auto-triage" not in captured.out
    assert "[triage]" not in captured.err


def test_triage_json_dry_run_and_schema_failure(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "triage-json"]) == 0
    capsys.readouterr()

    assert main(["triage", "triage-json", "--out", str(out_dir), "--dry-run", "--json"]) == 0
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_payload["command"] == "triage"
    assert dry_payload["dry_run"] is True
    assert dry_payload["triage"]["status"] == "dry_run"
    assert dry_payload["triage"]["selected_findings"] == 0

    install_fake_providers(tmp_path, judge_mode="gather", triage_source_id="F-001")
    failure_work_order = write_work_order(tmp_path, "gather")
    assert main(["research", str(failure_work_order), "--out", str(out_dir), "--run-id", "triage-json-fail"]) == 0
    capsys.readouterr()

    assert main(["triage", "triage-json-fail", "--out", str(out_dir), "--json"]) == 1
    captured = capsys.readouterr()
    failure_payload = json.loads(captured.out)
    assert failure_payload["status"] == "failed"
    assert failure_payload["triage"]["raw_status"] == "schema_error"
    assert "triage participant" not in captured.out


def test_runs_verify_success_latest_and_json(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"
    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "verify-run"]) == 0
    capsys.readouterr()

    assert main(["runs", "verify", "verify-run", "--out", str(out_dir)]) == 0
    human = capsys.readouterr().out
    assert "run verify: verify-run" in human
    assert "manifest: ok" in human
    assert "fingerprints: ok" in human

    assert main(["runs", "verify", "latest", "--out", str(out_dir), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "runs verify"
    assert payload["run_id"] == "verify-run"
    assert payload["required_artifacts"]["status"] == "ok"
    assert payload["fingerprints"]["checked_count"] > 0

    assert main(["runs", "verify", str(out_dir / "verify-run"), "--out", str(out_dir), "--json"]) == 0
    path_payload = json.loads(capsys.readouterr().out)
    assert path_payload["run_id"] == "verify-run"

    assert main(["runs", "verify", "../../etc", "--out", str(out_dir), "--json"]) == 2
    assert "run-id path must not contain . or .. segments" in capsys.readouterr().err


def test_runs_verify_failures_and_stale_triage(tmp_path, monkeypatch, capsys):
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather", facet={"id": "code-review"})
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "missing-manifest"]) == 0
    run_dir = out_dir / "missing-manifest"
    capsys.readouterr()
    (run_dir / "manifest.json").unlink()
    assert main(["runs", "verify", "missing-manifest", "--out", str(out_dir)]) == 1
    assert "missing manifest" in capsys.readouterr().out

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "missing-required"]) == 0
    run_dir = out_dir / "missing-required"
    capsys.readouterr()
    (run_dir / "report.md").unlink()
    assert main(["runs", "verify", "missing-required", "--out", str(out_dir)]) == 1
    assert "missing artifact" in capsys.readouterr().out

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "fingerprint-mismatch"]) == 0
    run_dir = out_dir / "fingerprint-mismatch"
    capsys.readouterr()
    (run_dir / "decision.json").write_text((run_dir / "decision.json").read_text() + "\n", encoding="utf-8")
    assert main(["runs", "verify", "fingerprint-mismatch", "--out", str(out_dir)]) == 1
    assert "fingerprint mismatch" in capsys.readouterr().out

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "stale-verify"]) == 0
    run_dir = out_dir / "stale-verify"
    capsys.readouterr()
    (run_dir / "decision.json").write_text((run_dir / "decision.json").read_text() + "\n", encoding="utf-8")
    write_run_manifest(run_dir)
    assert main(["runs", "verify", "stale-verify", "--out", str(out_dir), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["triage"]["state"] == "stale"
    assert payload["triage"]["stale_inputs"] == ["decision.json"]
    assert payload["next"].startswith("bakeoff triage stale-verify --force")


def test_no_color_for_json_surfaces(tmp_path, monkeypatch, capsys):
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    monkeypatch.setenv("NO_COLOR", "1")
    install_fake_providers(tmp_path, judge_mode="gather")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    work_order = write_work_order(tmp_path, "gather")
    out_dir = tmp_path / "runs"

    assert main(["research", str(work_order), "--out", str(out_dir), "--run-id", "plain-json", "--json"]) == 0
    research_output = "".join(capsys.readouterr())
    assert ansi.search(research_output) is None

    assert main(["triage", "plain-json", "--out", str(out_dir), "--dry-run", "--json"]) == 0
    triage_output = "".join(capsys.readouterr())
    assert ansi.search(triage_output) is None

    assert main(["runs", "verify", "plain-json", "--out", str(out_dir), "--json"]) == 0
    verify_output = "".join(capsys.readouterr())
    assert ansi.search(verify_output) is None


def init_git_repo(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "bakeoff@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Bakeoff Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    tracked.write_text("old\nnew\n", encoding="utf-8")


def install_fake_providers(
    tmp_path,
    *,
    judge_mode,
    fail_providers=frozenset(),
    fail_judge=False,
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
            fail_judge = {fail_judge!r}
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
            elif fail_judge and ("deduplication and conflict-flagging judge" in prompt or "pairwise judge" in prompt or "synthesis judge" in prompt):
                print("judge failed before final json", file=sys.stderr)
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


def write_work_order(tmp_path, mode, *, facet=None):
    scopes = ["codebase", "web"] if mode == "gather" else ["mixed", "mixed"]
    if facet and facet.get("id") == "code-review":
        scopes = ["codebase", "codebase"]
        facet = {
            "id": "code-review",
            "kind": "generic",
            "focus": "Find actionable defects introduced or exposed by the change.",
            "include": ["correctness bugs and edge cases"],
            "exclude": ["style-only preferences"],
        }
    elif facet:
        facet = {
            "id": facet["id"],
            "kind": "generic",
            "focus": "Find relevant facet evidence.",
            "include": ["relevant evidence"],
        }
    path = tmp_path / f"{mode}.json"
    data = {
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
    if facet:
        data["facet"] = facet
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
