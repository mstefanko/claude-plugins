import pytest

from bakeoff.cli import resolve_compare_decision, resolve_run_dir, validate_run_id
from bakeoff.work_order import ValidationError


def test_compare_pick_preserves_kept_material_from_both_swap_passes():
    decision = resolve_compare_decision(
        {"mode": "compare", "provider_statuses": {}},
        {
            "pass1": {
                "relation": "compare",
                "winner": "A",
                "rationale": "A wins pass 1",
                "kept_from_nonwinner": [{"claim": "codex useful pass1"}],
            },
            "pass2": {
                "relation": "compare",
                "winner": "B",
                "rationale": "B wins pass 2",
                "kept_from_nonwinner": [{"claim": "codex useful pass2"}],
            },
        },
        {"A": "claude", "B": "codex"},
        {"A": "codex", "B": "claude"},
    )

    assert decision["decision_kind"] == "pick_winner"
    assert decision["canonical_winner"] == "claude"
    assert [item["claim"] for item in decision["kept_from_nonwinner"]] == [
        "codex useful pass1",
        "codex useful pass2",
    ]


def test_compare_consensus_preserves_both_swap_passes():
    decision = resolve_compare_decision(
        {"mode": "compare", "provider_statuses": {}},
        {
            "pass1": {
                "relation": "consensus",
                "winner": None,
                "rationale": "consensus pass 1",
                "consensus_strongest": ["pass1 strongest"],
                "consensus_disagreements": ["pass1 disagreement"],
            },
            "pass2": {
                "relation": "consensus",
                "winner": None,
                "rationale": "consensus pass 2",
                "consensus_strongest": ["pass2 strongest"],
                "consensus_disagreements": ["pass2 disagreement"],
            },
        },
        {"A": "claude", "B": "codex"},
        {"A": "codex", "B": "claude"},
    )

    assert decision["decision_kind"] == "consensus"
    assert decision["consensus_strongest"] == ["pass1 strongest", "pass2 strongest"]
    assert decision["consensus_disagreements"] == ["pass1 disagreement", "pass2 disagreement"]


def test_compare_tie_preserves_material_from_each_unstable_pass():
    decision = resolve_compare_decision(
        {"mode": "compare", "provider_statuses": {}},
        {
            "pass1": {
                "relation": "compare",
                "winner": "A",
                "rationale": "A wins pass 1",
                "kept_from_nonwinner": [{"claim": "codex useful"}],
            },
            "pass2": {
                "relation": "compare",
                "winner": "A",
                "rationale": "A wins pass 2",
                "kept_from_nonwinner": [{"claim": "claude useful"}],
            },
        },
        {"A": "claude", "B": "codex"},
        {"A": "codex", "B": "claude"},
    )

    assert decision["decision_kind"] == "tie"
    assert decision["canonical_winner"] is None
    assert decision["kept_from_nonwinner"] == [
        {"claim": "codex useful", "source_provider": "codex"},
        {"claim": "claude useful", "source_provider": "claude"},
    ]


def test_run_id_rejects_path_traversal():
    with pytest.raises(ValidationError):
        validate_run_id("../outside")


def test_resolve_latest_supports_text_fallback(tmp_path):
    run_dir = tmp_path / "2026-05-14-abcd"
    run_dir.mkdir()
    (tmp_path / "latest").write_text("2026-05-14-abcd\n", encoding="utf-8")

    assert resolve_run_dir(tmp_path, "latest") == run_dir
