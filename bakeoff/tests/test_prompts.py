from bakeoff.providers import build_judge_prompt, build_worker_prompt


def _work_order(mode):
    return {
        "type": mode,
        "goal": "Find gaps.",
        "background": "Use the repo.",
    }


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
