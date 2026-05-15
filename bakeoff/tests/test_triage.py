from bakeoff.cli import write_json
from bakeoff.triage import (
    check_citations,
    compute_input_hashes,
    extract_citations_from_text,
    resolve_citation_cwd,
    should_recommend_triage,
    triage_state,
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
