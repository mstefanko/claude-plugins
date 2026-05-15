import json

import pytest

from bakeoff.work_order import (
    MODE_EFFORT_DEFAULTS,
    ValidationError,
    init_template,
    load_work_order,
    review_template,
    strip_jsonc_comments,
    validate_analyze_judge_result,
    validate_compare_judge_result,
    validate_gather_judge_result,
    validate_triage_result,
)


def test_jsonc_state_machine_preserves_comment_markers_in_strings():
    raw = r'''
    {
      // comment
      "url": "https://example.com/a//b",
      "glob": "literal /* not comment */ marker",
      "quote": "escaped \" quote",
      "slash": "backslash \\ before quote"
    }
    '''

    parsed = json.loads(strip_jsonc_comments(raw))

    assert parsed["url"] == "https://example.com/a//b"
    assert parsed["glob"] == "literal /* not comment */ marker"
    assert parsed["quote"] == 'escaped " quote'
    assert parsed["slash"] == "backslash \\ before quote"


def test_validates_work_order_and_defaults_effort(tmp_path):
    path = tmp_path / "wo.jsonc"
    path.write_text(
        """
        {
          "schema_version": 1,
          "id": "routing",
          "type": "gather",
          "goal": "Find routing facts.",
          "background": "Use https://example.com/docs.",
          "providers": [
            { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "scope": "codebase" },
            { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "web" }
          ],
          "judge": { "backend": "claude", "model": "claude-opus-4-7" },
          "budgets": { "wall_clock_seconds": 3, "max_output_bytes": 2000 }
        }
        """,
        encoding="utf-8",
    )

    work_order = load_work_order(path)

    assert work_order["providers"][0]["effort"] == "high"
    assert work_order["judge"]["effort"] == "high"
    assert work_order["budgets"]["heartbeat_seconds"] == 60
    assert work_order["budgets"]["output_cap_grace_seconds"] == 10
    assert work_order["budgets"]["max_output_overrun_bytes"] == 2000
    assert work_order["scope_policy"] == {"enforcement": "best_effort"}


def test_accepts_xhigh_effort(tmp_path):
    path = tmp_path / "wo.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "routing",
                "type": "gather",
                "goal": "Find routing facts.",
                "background": "",
                "providers": [
                    {
                        "id": "claude",
                        "backend": "claude",
                        "model": "claude-sonnet-4-6",
                        "scope": "codebase",
                        "effort": "high",
                    },
                    {
                        "id": "codex",
                        "backend": "codex",
                        "model": "gpt-5.5",
                        "scope": "web",
                        "effort": "xhigh",
                    },
                ],
                "judge": {"backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh"},
                "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000},
            }
        ),
        encoding="utf-8",
    )

    work_order = load_work_order(path)

    assert work_order["providers"][1]["effort"] == "xhigh"
    assert work_order["judge"]["effort"] == "xhigh"


def test_validates_scope_policy(tmp_path):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "scope_policy": {"enforcement": "required"},
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000},
    }
    path = tmp_path / "wo.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert load_work_order(path)["scope_policy"] == {"enforcement": "required"}

    data["scope_policy"] = {"enforcement": "strict"}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="scope_policy.enforcement"):
        load_work_order(path)


def test_validates_optional_facet(tmp_path):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "facet": {
            "id": "security",
            "focus": "Find reachable security risks.",
            "include": ["authorization\x00regressions"],
            "exclude": ["generic advice"],
            "notes": "Only\tchanged auth paths.",
        },
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000},
    }
    path = tmp_path / "wo.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    work_order = load_work_order(path)

    assert work_order["facet"] == {
        "id": "security",
        "kind": "generic",
        "focus": "Find reachable security risks.",
        "include": ["authorization regressions"],
        "exclude": ["generic advice"],
        "notes": "Only changed auth paths.",
    }


@pytest.mark.parametrize(
    ("facet", "message"),
    [
        ([], "facet must be an object"),
        ({"id": "security", "focus": "Find risks.", "include": ["x"], "extra": True}, "unsupported keys"),
        ({"id": "bad id", "focus": "Find risks.", "include": ["x"]}, "facet.id must be a slug"),
        ({"id": "security", "kind": "roleplay", "focus": "Find risks.", "include": ["x"]}, 'facet.kind must be "generic"'),
        ({"id": "security", "focus": "", "include": ["x"]}, "facet.focus must be a non-empty string"),
        ({"id": "security", "focus": "Find risks.", "include": []}, "facet.include must contain 1-8 items"),
        ({"id": "security", "focus": "Find risks.", "include": [""]}, r"facet.include\[0\] must be a non-empty string"),
        ({"id": "judge", "focus": "Find risks.", "include": ["x"]}, "facet.id is reserved"),
        ({"id": "security", "focus": "x" * 501, "include": ["x"]}, "facet.focus must be at most 500 characters"),
        ({"id": "security", "focus": "Find risks </facet>.", "include": ["x"]}, r"facet.focus must not contain </facet>"),
        ({"id": "security", "focus": "Find risks <facet>.", "include": ["x"]}, "facet.focus must not contain angle brackets"),
        ({"id": "security", "focus": "Find risks.", "include": ["`x`"]}, r"facet.include\[0\] must not contain backticks"),
        ({"id": "security", "focus": "Find risks.", "include": ["x"], "notes": ""}, "facet.notes must be a non-empty string"),
        (
            {
                "id": "security",
                "focus": "x",
                "include": ["x" * 260] * 8,
                "exclude": ["x" * 260] * 8,
            },
            "facet text must be at most 4096 characters total",
        ),
    ],
)
def test_facet_validation_errors_name_field(tmp_path, facet, message):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "facet": facet,
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000},
    }
    path = tmp_path / "bad-facet.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        load_work_order(path)


def test_rejects_provider_level_facets_and_id_collision(tmp_path):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "facet": {"id": "claude", "focus": "Find risks.", "include": ["x"]},
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000},
    }
    path = tmp_path / "bad-facet.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="facet.id must not duplicate a provider id"):
        load_work_order(path)

    data["facet"]["id"] = "security"
    data["providers"][0]["facet"] = {"id": "provider-security"}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match=r"providers\[0\]\.facet is not supported"):
        load_work_order(path)


@pytest.mark.parametrize("mode", sorted(MODE_EFFORT_DEFAULTS))
def test_init_template_uses_mode_effort_defaults(mode):
    template = init_template(mode)
    data = json.loads(strip_jsonc_comments(template))
    defaults = MODE_EFFORT_DEFAULTS[mode]

    assert data["providers"][0]["effort"] == defaults["worker"]
    assert data["providers"][1]["effort"] == defaults["worker"]
    assert data["judge"]["effort"] == defaults["judge"]


def test_review_template_is_gather_work_order_with_code_review_facet():
    data = json.loads(strip_jsonc_comments(review_template()))

    assert data["type"] == "gather"
    assert data["facet"]["id"] == "code-review"
    assert [provider["scope"] for provider in data["providers"]] == ["codebase", "codebase"]
    assert [provider["effort"] for provider in data["providers"]] == ["high", "high"]
    assert data["judge"]["effort"] == "xhigh"


def test_budget_heartbeat_seconds_must_not_be_negative(tmp_path):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000, "heartbeat_seconds": -1},
    }
    path = tmp_path / "bad-heartbeat.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError, match="budgets.heartbeat_seconds"):
        load_work_order(path)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("output_cap_grace_seconds", "budgets.output_cap_grace_seconds"),
        ("max_output_overrun_bytes", "budgets.max_output_overrun_bytes"),
    ],
)
def test_output_cap_budget_fields_must_not_be_negative(tmp_path, field, message):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000, field: -1},
    }
    path = tmp_path / f"bad-{field}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        load_work_order(path)


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"id": "TODO-rename-this"}, "id must not match"),
        ({"type": "build"}, "type must be one of"),
        (
            {
                "providers": [
                    {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
                    {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
                    {"id": "third", "backend": "codex", "model": "third", "scope": "web"},
                ]
            },
            "providers must have exactly 2 entries",
        ),
        (
            {
                "providers": [
                    {"id": "../claude", "backend": "claude", "model": "same", "scope": "codebase"},
                    {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
                ]
            },
            "providers\\[0\\].id must be a slug",
        ),
    ],
)
def test_validation_errors_name_field(tmp_path, patch, message):
    data = {
        "schema_version": 1,
        "id": "routing",
        "type": "gather",
        "goal": "Find routing facts.",
        "background": "",
        "providers": [
            {"id": "claude", "backend": "claude", "model": "same", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "other", "scope": "web"},
        ],
        "judge": {"backend": "claude", "model": "judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 2000},
    }
    data.update(patch)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        load_work_order(path)


def test_compare_judge_scores_must_match_rubric_shape():
    result = {
        "relation": "compare",
        "scores_a": {"evidence": 5, "coherence": 5, "tradeoff_honesty": 5, "rebuttals": 5},
        "scores_b": {"evidence": 4, "coherence": 4, "tradeoff_honesty": 4, "rebuttals": 4},
        "winner": "A",
        "rationale": "A is better evidenced.",
        "kept_from_nonwinner": [],
        "consensus_strongest": [],
        "consensus_disagreements": [],
    }

    assert validate_compare_judge_result(result) == result

    result["scores_a"]["evidence"] = 6
    with pytest.raises(ValidationError, match="scores_a.evidence"):
        validate_compare_judge_result(result)


def test_gather_judge_validates_out_of_facet_claim_shape():
    result = {
        "merged_claims": [
            {
                "claim": "Security finding.",
                "evidence": ["src/app.py:1"],
                "sources": ["A"],
                "confidence": "high",
            }
        ],
        "conflicts": [],
        "unknowns_union": [],
        "out_of_facet_claims": [
            {
                "claim": "Out-of-facet issue.",
                "evidence": ["src/app.py:2"],
                "sources": ["B"],
                "reason": "outside the facet",
            }
        ],
    }

    assert validate_gather_judge_result(result) == result

    result["out_of_facet_claims"][0]["sources"] = ["C"]
    with pytest.raises(ValidationError, match="out_of_facet_claims\\[0\\]\\.sources"):
        validate_gather_judge_result(result)

    result["out_of_facet_claims"][0]["sources"] = ["B"]
    result["merged_claims"][0]["sources"] = []
    with pytest.raises(ValidationError, match="merged_claims\\[0\\]\\.sources"):
        validate_gather_judge_result(result)


def test_analyze_judge_verdicts_must_match_overlay_shape():
    result = {
        "scores_a": {"step_atomicity": 5, "citation_grounding": 5, "assumption_transparency": 4, "coherence": 5},
        "scores_b": {"step_atomicity": 4, "citation_grounding": 4, "assumption_transparency": 4, "coherence": 4},
        "spine_winner": "A",
        "spine_rationale": "A is clearer.",
        "claim_verdicts": [{"claim_id": "R-001", "loser_position": "agrees", "loser_note": "same claim"}],
        "additions_from_loser": [{"claim": "extra nuance", "evidence": ["fake:1"]}],
        "actionable_followups": [
            {
                "claim": "Add a regression test.",
                "kind": "test_gap",
                "severity": "low",
                "evidence": ["tests/test_runner.py:1"],
                "recommended_action": "defer",
            }
        ],
    }

    assert validate_analyze_judge_result(result) == result

    result["claim_verdicts"][0]["loser_position"] = "maybe"
    with pytest.raises(ValidationError, match="loser_position"):
        validate_analyze_judge_result(result)


def test_triage_result_must_match_schema_shape():
    result = {
        "schema_version": 1,
        "status": "complete",
        "summary": "checked",
        "items": [
            {
                "id": "T-001",
                "source_finding_id": "F-001",
                "source_finding": "bug",
                "classification": "real_issue",
                "severity": "medium",
                "confidence": "high",
                "supporting_evidence": ["src/app.py:1"],
                "counterevidence": [],
                "citation_check_ids": ["C-001"],
                "recommended_action": "fix_now",
                "rationale": "actionable",
            }
        ],
        "unknowns": [],
    }

    assert validate_triage_result(result) == result

    result["items"][0]["classification"] = "maybe"
    with pytest.raises(ValidationError, match="classification"):
        validate_triage_result(result)
