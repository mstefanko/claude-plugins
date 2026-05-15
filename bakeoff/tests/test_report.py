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


def test_faceted_gather_report_labels_facet_and_out_of_facet_claims_without_finding_ids():
    report = render_report(
        {
            "id": "r",
            "type": "gather",
            "facet": {
                "id": "security",
                "focus": "Find concrete security risks.",
                "include": ["auth regressions"],
            },
        },
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
                        "claim": "Security finding.",
                        "evidence": ["a:1"],
                        "sources": ["A"],
                        "confidence": "medium",
                    }
                ],
                "conflicts": [],
                "unknowns_union": [],
                "out_of_facet_claims": [
                    {
                        "claim": "Out-of-facet bug should not be triaged.",
                        "evidence": ["b:2"],
                        "sources": ["B"],
                        "reason": "outside security facet",
                    }
                ],
            }
        },
    )

    assert "Facet: `security`" in report
    assert "Facet Focus: Find concrete security risks." in report
    assert "Provider-set headings name the worker set that surfaced each claim." in report
    assert "within the shared `security` facet; it is not proof of correctness" in report
    assert "## Out-of-Facet Claims" in report
    assert "excluded from triage source selection" in report
    assert "Out-of-facet bug should not be triaged." in report
    assert "**F-001** Security finding." in report
    assert "**F-002** Out-of-facet bug" not in report


def test_out_of_facet_report_handles_malformed_items_defensively():
    report = render_report(
        {"id": "r", "type": "gather", "facet": {"id": "security", "focus": "Find risks.", "include": ["risks"]}},
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
                "merged_claims": [],
                "conflicts": [],
                "unknowns_union": [],
                "out_of_facet_claims": ["raw item", {"evidence": ["x:1"]}],
            }
        },
    )

    assert "raw item" in report
    assert "Evidence: x:1" in report


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
