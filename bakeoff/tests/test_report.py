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


def test_gather_report_derives_corroboration_from_sources():
    report = render_report(
        {"id": "r", "type": "gather"},
        {
            "mode": "gather",
            "decision_kind": "structured_union",
            "judge_ran": True,
            "provider_statuses": {},
            "order_maps": {"pass1": {"A": "claude", "B": "codex"}},
        },
        {},
        judge_results={
            "pass1": {
                "merged_claims": [
                    {
                        "claim": "Both found this.",
                        "evidence": ["a:1", "b:2"],
                        "sources": ["A", "B"],
                        "confidence": "high",
                    },
                    {
                        "claim": "Only one found this.",
                        "evidence": ["a:3"],
                        "sources": ["A"],
                        "confidence": "high",
                    },
                ],
                "conflicts": [],
                "unknowns_union": [],
            }
        },
    )

    assert "model confidence `high`, corroboration `multi-source`, sources `claude+codex`" in report
    assert "model confidence `high`, corroboration `single-source`, sources `claude`" in report


def test_analyze_report_numbers_actionable_followups_not_explanation_inventory():
    report = render_report(
        {"id": "r", "type": "analyze"},
        {
            "mode": "analyze",
            "decision_kind": "pick_winner",
            "judge_ran": True,
            "provider_statuses": {},
            "canonical_winner": "codex",
            "claim_verdicts": [],
            "actionable_followups": [
                {
                    "claim": "Add a cancellation regression test.",
                    "kind": "test_gap",
                    "severity": "low",
                    "evidence": ["tests/test_runner.py:1"],
                    "recommended_action": "defer",
                }
            ],
        },
        {
            "codex": {
                "final_json": {
                    "claims": [
                        {
                            "id": "R-001",
                            "claim": "The runner records provider status.",
                            "evidence": ["src/bakeoff/runner.py:1"],
                            "confidence": "high",
                        }
                    ]
                }
            }
        },
    )

    assert "- **R-001** The runner records provider status." in report
    assert "- **F-001** Add a cancellation regression test." in report
