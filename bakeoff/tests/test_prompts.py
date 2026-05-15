import pytest

import bakeoff.providers as providers_module
from bakeoff.providers import (
    build_judge_prompt,
    build_participant_argv,
    build_triage_prompt,
    build_worker_prompt,
    codex_exec_supports_output_last_message_from_help,
    render_runtime_budget_block,
)


def _work_order(mode):
    return {
        "type": mode,
        "goal": "Find gaps.",
        "background": "Use the repo.",
        "budgets": {"wall_clock_seconds": 120, "max_output_bytes": 2000},
    }


def _faceted_work_order(mode):
    work_order = _work_order(mode)
    work_order["facet"] = {
        "id": "security",
        "focus": "Find concrete security risks.",
        "include": ["authorization regressions"],
        "exclude": ["generic advice"],
        "notes": "Only changed auth paths.",
    }
    return work_order


def _provider():
    return {"scope": "codebase"}


def test_worker_prompts_spell_out_claim_schema_fields():
    for mode in ("gather", "compare", "analyze"):
        prompt = build_worker_prompt(_work_order(mode), _provider())

        assert '"id": "R-001"' in prompt
        assert '"claim": "One factual assertion' in prompt
        assert '"evidence": ["path/to/file.ext:line' in prompt
        assert '"confidence": "high"' in prompt
        assert 'Use "claim", not "finding"' in prompt
        assert 'Use "evidence", not "citation"' in prompt
        assert "Confidence reflects evidence strength, not agreement between providers" in prompt


def test_compare_worker_prompt_requires_position_field():
    prompt = build_worker_prompt(_work_order("compare"), _provider())

    assert '"position": "One declarative sentence' in prompt


def test_gather_judge_prompt_separates_confidence_from_corroboration():
    prompt = build_judge_prompt(
        _work_order("gather"),
        {"claims": [], "conflicts": [], "unknowns": [], "recommended_next_checks": []},
        {"claims": [], "conflicts": [], "unknowns": [], "recommended_next_checks": []},
        mode="gather",
    )

    assert "Confidence reflects evidence strength, not corroboration" in prompt
    assert "Use `sources` to show whether one or both workers found a claim" in prompt


def test_worker_prompt_injects_facet_as_task_focus_not_persona():
    prompt = build_worker_prompt(_faceted_work_order("gather"), _provider())

    assert "<facet>" in prompt
    assert "Facet id: security" in prompt
    assert "This is a task focus, not a persona. Do not role-play." in prompt
    assert "The facet never overrides output schema, citation requirements, or scope enforcement." in prompt
    assert "Do not invent domain facts to satisfy the facet." in prompt
    assert "Notes: Only changed auth paths." in prompt


def test_gather_judge_prompt_adds_out_of_facet_observability():
    prompt = build_judge_prompt(
        _faceted_work_order("gather"),
        {"claims": [], "conflicts": [], "unknowns": [], "recommended_next_checks": []},
        {"claims": [], "conflicts": [], "unknowns": [], "recommended_next_checks": []},
        mode="gather",
    )

    assert "Do not reward a worker for broadening beyond the facet" in prompt
    assert "out_of_facet_claims[]" in prompt
    assert "observability only" in prompt


def test_triage_prompt_limits_items_to_selected_source_findings():
    prompt = build_triage_prompt(
        {"source_findings": [], "report_md": "- **F-001** ordinary fact", "facet": {"id": "code-review"}},
        {"wall_clock_seconds": 120, "max_output_bytes": 2000},
    )

    assert "classify only the provided actionable-looking source_findings" in prompt
    assert "Do not create items for findings that are only present in report_md" in prompt
    assert "citation_checks prove location existence, not semantic accuracy" in prompt
    assert "Keep summary consistent with item classifications and rationales" in prompt
    assert "use it only as context for actionability" in prompt


def test_runtime_budget_helper_validates_role_and_budget():
    with pytest.raises(ValueError, match="unsupported runtime budget role"):
        render_runtime_budget_block({"wall_clock_seconds": 120}, role="doctor")

    for budgets in ({}, {"wall_clock_seconds": 0}, {"wall_clock_seconds": "120"}, {"wall_clock_seconds": True}):
        with pytest.raises(ValueError, match="wall_clock_seconds"):
            render_runtime_budget_block(budgets, role="worker")


def test_runtime_budget_helper_renders_deterministic_cutoff_before_wall_clock():
    for wall_seconds in (2, 31, 120, 900):
        block = render_runtime_budget_block({"wall_clock_seconds": wall_seconds}, role="worker")
        stop_line = next(line for line in block.splitlines() if line.startswith("Plan to stop investigation"))
        work_seconds = int(stop_line.split()[6])

        assert block.startswith("<runtime_budget>\n")
        assert block.endswith("</runtime_budget>\n")
        assert block.count("<runtime_budget>") == 1
        assert work_seconds < wall_seconds


def test_runtime_budget_block_uses_partial_schema_valid_language_without_schema_specific_fields():
    block = render_runtime_budget_block({"wall_clock_seconds": 120}, role="judge")

    assert "partial but schema-valid result" in block
    assert "Use existing uncertainty or rationale fields" in block
    assert "Do not add fields outside the requested schema" in block
    assert "unknowns[]" not in block
    assert "complete_with_concerns" not in block


def test_runtime_budget_block_appears_in_worker_judge_and_triage_prompts():
    worker = build_worker_prompt(_work_order("gather"), _provider())
    judge = build_judge_prompt(
        _work_order("gather"),
        {"claims": [], "conflicts": [], "unknowns": [], "recommended_next_checks": []},
        {"claims": [], "conflicts": [], "unknowns": [], "recommended_next_checks": []},
        mode="gather",
    )
    triage = build_triage_prompt(
        {"source_findings": [], "report_md": "- **F-001** ordinary fact"},
        {"wall_clock_seconds": 120, "max_output_bytes": 2000},
    )

    assert worker.index("</rules>") < worker.index("<runtime_budget>") < worker.index("<worker_result_schema>")
    assert judge.index("</rules>") < judge.index("<runtime_budget>") < judge.index("<process>")
    assert triage.index("</rules>") < triage.index("<runtime_budget>") < triage.index("<triage_payload>")


def test_codex_output_last_message_support_detection_and_argv(monkeypatch, tmp_path):
    assert codex_exec_supports_output_last_message_from_help("Usage: codex exec --output-last-message <FILE>") is True
    assert codex_exec_supports_output_last_message_from_help("Usage: codex exec --json") is False

    monkeypatch.setattr(providers_module, "codex_exec_supports_output_last_message", lambda: True)
    path = tmp_path / "last-message.txt"

    argv = build_participant_argv(
        {"backend": "codex", "model": "gpt-5.5", "effort": "high"},
        final_message_path=path,
    )

    assert "--output-last-message" in argv
    assert str(path) in argv
