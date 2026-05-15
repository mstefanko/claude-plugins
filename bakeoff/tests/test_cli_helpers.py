from bakeoff.cli import merge_items


def test_merge_items_dedupes_near_duplicate_preserved_claims_from_same_source():
    items = merge_items(
        [
            {
                "claim": "Advisory failures are detectable post-hoc via triage citation checks, while hard enforcement failures can destroy a data point.",
                "source_provider": "claude",
            }
        ],
        [
            {
                "claim": "Advisory's soft-failure is post-hoc detectable via triage citation checks while enforcement hard-failures destroy the data point.",
                "source_provider": "claude",
            }
        ],
    )

    assert len(items) == 1


def test_merge_items_keeps_similar_claims_from_different_sources():
    items = merge_items(
        [{"claim": "Scope should be enforced when possible.", "source_provider": "claude"}],
        [{"claim": "Scope should be enforced when possible.", "source_provider": "codex"}],
    )

    assert len(items) == 2
