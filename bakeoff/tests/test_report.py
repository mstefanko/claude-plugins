from bakeoff.report import render_report


def test_report_surfaces_compare_nonwinner_material():
    report = render_report(
        {"id": "r", "type": "compare"},
        {
            "mode": "compare",
            "decision_kind": "pick_winner",
            "judge_ran": True,
            "provider_statuses": {},
            "canonical_winner": "claude",
            "kept_from_nonwinner": [{"claim": "keep this", "source_provider": "codex"}],
        },
        {
            "claude": {
                "final_json": {
                    "position": "Use X",
                    "claims": [{"id": "R-1", "claim": "X is better", "evidence": ["a:1"], "confidence": "high"}],
                }
            }
        },
    )

    assert "## Kept From Nonwinner" in report
    assert "**F-001** X is better" in report
    assert "**F-002** keep this" in report
    assert "keep this" in report
    assert "Source: `codex`" in report
