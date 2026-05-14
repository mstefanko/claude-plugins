from bakeoff.providers import build_worker_prompt


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


def test_compare_worker_prompt_requires_position_field():
    prompt = build_worker_prompt(_work_order("compare"), _provider())

    assert '"position": "One declarative sentence' in prompt
