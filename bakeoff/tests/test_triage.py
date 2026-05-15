from bakeoff.cli import write_json
from bakeoff.triage import (
    check_citations,
    compute_input_hashes,
    extract_citations_from_text,
    render_triage_markdown,
    resolve_citation_cwd,
    select_triage_source_findings,
    should_auto_triage,
    should_recommend_triage,
    summarize_source_finding_filter,
    triage_state,
    triage_state_detail,
)


def test_citation_extraction_skips_urls_and_handles_ranges(tmp_path):
    absolute = tmp_path / "abs.py"
    text = f"See src/app.py:2 and src/app.py:2-3 and {absolute}:1 but not https://example.com/app.py:1"

    assert extract_citations_from_text(text) == ["src/app.py:2", "src/app.py:2-3", f"{absolute}:1"]


def test_citation_checks_record_ok_missing_range_and_escape(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "src" / "app.py"
    absolute_outside = tmp_path / "outside.py"
    source.parent.mkdir(parents=True)
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    absolute_outside.write_text("secret\n", encoding="utf-8")

    checks = check_citations(
        ["src/app.py:2", "src/missing.py:1", "src/app.py:99", "../outside.py:1", f"{absolute_outside}:1"],
        repo.resolve(),
    )["checks"]

    assert [check["status"] for check in checks] == [
        "ok",
        "missing_file",
        "line_out_of_range",
        "path_escape",
        "path_escape",
    ]
    assert "two" in checks[0]["excerpt"]


def test_resolve_citation_cwd_rejects_missing_or_file_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = tmp_path / "not-a-dir"
    file_path.write_text("x", encoding="utf-8")

    cwd, caveats = resolve_citation_cwd({"cwd": str(file_path)})

    assert cwd == tmp_path.resolve()
    assert caveats == ["original cwd from meta.json is not a directory; using current working directory for citation checks"]


def test_triage_state_marks_changed_inputs_stale(tmp_path):
    run_dir = tmp_path / "run"
    triage_dir = run_dir / "triage"
    triage_dir.mkdir(parents=True)
    (run_dir / "work-order.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "decision.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "report.md").write_text("old\n", encoding="utf-8")
    write_json(
        triage_dir / "final.json",
        {
            "input_hashes": compute_input_hashes(run_dir),
        },
    )
    (triage_dir / "triage.md").write_text("# ok\n", encoding="utf-8")

    assert triage_state(run_dir) == "yes"

    (run_dir / "report.md").write_text("new\n", encoding="utf-8")

    assert triage_state(run_dir) == "stale"
    assert triage_state_detail(run_dir) == ("stale", ["report.md"])

    write_json(
        triage_dir / "final.json",
        {
            "input_hashes": compute_input_hashes(run_dir),
        },
    )
    (run_dir / "work-order.json").write_text('{"facet":{"id":"security"}}\n', encoding="utf-8")

    assert triage_state(run_dir) == "stale"
    assert triage_state_detail(run_dir) == ("stale", ["work-order.json"])


def test_triage_state_accepts_legacy_hashes_without_work_order_sha(tmp_path):
    run_dir = tmp_path / "run"
    triage_dir = run_dir / "triage"
    triage_dir.mkdir(parents=True)
    (run_dir / "work-order.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "decision.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "report.md").write_text("old\n", encoding="utf-8")
    hashes = compute_input_hashes(run_dir)
    hashes.pop("work_order_sha256")
    write_json(triage_dir / "final.json", {"input_hashes": hashes})
    (triage_dir / "triage.md").write_text("# ok\n", encoding="utf-8")

    assert triage_state(run_dir) == "yes"


def test_triage_state_reports_dry_run_without_final_report(tmp_path):
    run_dir = tmp_path / "run"
    triage_dir = run_dir / "triage"
    triage_dir.mkdir(parents=True)
    write_json(triage_dir / "status.json", {"status": "dry_run"})

    assert triage_state(run_dir) == "dry_run"


def test_recommendation_uses_word_boundaries():
    assert should_recommend_triage({"type": "gather"}, {"decision_kind": "structured_union"}, "vintage report") is None
    assert should_recommend_triage({"type": "gather"}, {"decision_kind": "structured_union"}, "- **F-001** missing docs")
    assert should_recommend_triage({"type": "compare"}, {"decision_kind": "pick_winner"}, "- **F-001** should consider docs") is None
    assert (
        should_recommend_triage(
            {"type": "compare"},
            {"decision_kind": "pick_winner"},
            "## Decision Audit\n\n- Judge rationale: should fix maybe\n\n## Comparison\n\n- **F-001** stable choice",
        )
        is None
    )


def test_code_review_facet_recommends_and_auto_triages():
    work_order = {"type": "gather", "facet": {"id": "code-review"}}
    decision = {"decision_kind": "structured_union"}

    assert should_auto_triage(work_order, decision) == "code-review facet - verify actionable findings before fixing"
    assert should_recommend_triage(work_order, decision, "") == "code-review facet - verify actionable findings before fixing"
    assert should_auto_triage({"type": "gather"}, decision) is None
    assert should_auto_triage({"type": "analyze", "facet": {"id": "code-review"}}, decision) is None
    assert should_auto_triage(work_order, {"decision_kind": "both_failed"}) is None
    assert should_auto_triage(work_order, {"decision_kind": "single_provider_only"}) is None
    assert should_auto_triage(work_order, {"decision_kind": "tie"}) is None


def test_select_triage_source_findings_skips_plain_findings():
    findings = [
        {"id": "F-001", "section": "Findings", "text": "Provider status is stored in status.json."},
        {"id": "F-002", "section": "Findings", "text": "Report mentions a missing citation."},
        {"id": "F-003", "section": "Conflicts", "text": "Workers disagree about exit codes."},
        {"id": "F-004", "section": "Unknowns", "text": "Whether tests cover triage."},
    ]

    selected, skipped = select_triage_source_findings(findings)

    assert [finding["id"] for finding in selected] == ["F-002", "F-003", "F-004"]
    assert [finding["id"] for finding in skipped] == ["F-001"]


def test_code_review_facet_selects_all_findings_for_triage():
    findings = [
        {"id": "F-001", "section": "Findings", "text": "Provider status is stored in status.json."},
        {"id": "F-002", "section": "Findings", "text": "Report mentions a missing citation."},
        {"id": "F-003", "section": "Out-of-Facet Claims", "text": "Out of facet bug."},
    ]

    selected, skipped = select_triage_source_findings(findings, facet_id="code-review")

    assert [finding["id"] for finding in selected] == ["F-001", "F-002"]
    assert [finding["id"] for finding in skipped] == ["F-003"]


def test_any_facet_selects_findings_for_triage():
    findings = [
        {"id": "F-001", "section": "Findings", "text": "The stale-state copy lacks recovery context."},
        {"id": "F-002", "section": "Findings", "text": "The ls output omits the facet column."},
        {"id": "F-003", "section": "Out-of-Facet Claims", "text": "Unrelated bug."},
    ]

    selected, skipped = select_triage_source_findings(findings, facet_id="operator-ux")

    assert [finding["id"] for finding in selected] == ["F-001", "F-002"]
    assert [finding["id"] for finding in skipped] == ["F-003"]
    assert summarize_source_finding_filter(selected, skipped) == {
        "included": 2,
        "skipped_non_actionable": 0,
        "skipped_out_of_facet": 1,
    }


def test_select_triage_source_findings_filters_analyze_inventory():
    findings = [
        {
            "id": "F-001",
            "section": "Primary Explanation",
            "text": "For zero-exit processes, ValidationError becomes schema_error.",
        },
        {
            "id": "F-002",
            "section": "Primary Explanation",
            "text": "README documentation names timeout statuses, but the runner also has missing_provider.",
        },
        {
            "id": "F-003",
            "section": "Primary Explanation",
            "text": "Missing coverage: no test exercises cancellation.",
        },
        {
            "id": "F-004",
            "section": "Actionable Follow-ups",
            "text": "Add an output-cap grace regression test.",
        },
    ]

    selected, skipped = select_triage_source_findings(findings)

    assert [finding["id"] for finding in selected] == ["F-002", "F-003", "F-004"]
    assert [finding["id"] for finding in skipped] == ["F-001"]


def test_select_triage_source_findings_skips_out_of_facet_claims():
    findings = [
        {"id": "F-001", "section": "Out-of-Facet Claims", "text": "Out of facet bug."},
        {"id": "F-002", "section": "Conflicts", "text": "Workers disagree."},
    ]

    selected, skipped = select_triage_source_findings(findings)

    assert [finding["id"] for finding in selected] == ["F-002"]
    assert [finding["id"] for finding in skipped] == ["F-001"]
    assert skipped[0]["skip_reason"] == "out_of_facet"


def test_select_triage_source_findings_catches_operator_ux_language():
    findings = [
        {"id": "F-001", "section": "Findings", "text": "The recovery command is misleading."},
        {"id": "F-002", "section": "Findings", "text": "The triage state label is ambiguous."},
        {"id": "F-003", "section": "Findings", "text": "Provider status is stored in status.json."},
    ]

    selected, skipped = select_triage_source_findings(findings)

    assert [finding["id"] for finding in selected] == ["F-001", "F-002"]
    assert [finding["id"] for finding in skipped] == ["F-003"]


def test_should_recommend_triage_ignores_descriptive_analyze_inventory():
    report = "## Primary Explanation\n\n- **F-001** For zero-exit processes, ValidationError becomes schema_error.\n"

    assert should_recommend_triage({"type": "analyze"}, {"decision_kind": "pick_winner"}, report) is None


def test_triage_markdown_renders_each_item_once_by_priority():
    final = {
        "run_id": "run",
        "summary": "checked",
        "items": [
            {
                "id": "T-001",
                "source_finding": "conflict",
                "classification": "false_positive",
                "recommended_action": "document",
                "rationale": "not a bug",
            },
            {
                "id": "T-002",
                "source_finding": "unknown",
                "classification": "evidence_gap",
                "recommended_action": "defer",
                "rationale": "needs evidence",
            },
            {
                "id": "T-003",
                "source_finding": "already done",
                "classification": "already_fixed",
                "recommended_action": "ignore",
                "rationale": "fixed before triage",
            },
            {
                "id": "T-004",
                "source_finding": "unsupported action pairing",
                "classification": "real_issue",
                "recommended_action": "ignore",
                "rationale": "schema-valid but uncategorized",
            },
        ],
        "unknowns": [],
    }

    markdown = render_triage_markdown(final, [])

    assert markdown.count("[T-001]") == 1
    assert markdown.count("[T-002]") == 1
    assert markdown.count("[T-003]") == 1
    assert markdown.count("[T-004]") == 1
    assert "## False Positives\n\n- [T-001]" in markdown
    assert "## Needs Reproduction\n\n- [T-002]" in markdown
    assert "## Already Fixed\n\n- [T-003]" in markdown
    assert "## False Positives\n\n- [T-003]" not in markdown
    assert "## Other Valid Items\n\n- [T-004]" in markdown
