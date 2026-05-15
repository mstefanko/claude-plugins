from bakeoff.providers import build_judge_prompt, build_triage_prompt, build_worker_prompt


def _work_order(mode):
    return {
        "type": mode,
        "goal": "Find gaps.",
        "background": "Use the repo.",
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
    prompt = build_triage_prompt({"source_findings": [], "report_md": "- **F-001** ordinary fact", "facet": {"id": "code-review"}})

    assert "classify only the provided actionable-looking source_findings" in prompt
    assert "Do not create items for findings that are only present in report_md" in prompt
    assert "citation_checks prove location existence, not semantic accuracy" in prompt
    assert "Keep summary consistent with item classifications and rationales" in prompt
    assert "use it only as context for actionability" in prompt
