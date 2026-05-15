from bakeoff.cli import merge_items


def test_merge_items_dedupes_normalized_duplicate_preserved_claims_from_same_source():
    items = merge_items(
        [
            {
                "claim": "Scope should be enforced when possible.",
                "source_provider": "claude",
            }
        ],
        [
            {
                "claim": "Scope should be enforced when possible!",
                "source_provider": "claude",
            }
        ],
    )

    assert len(items) == 1


def test_merge_items_keeps_near_duplicates_when_numbers_change():
    items = merge_items(
        [{"claim": "The change improves latency by 10%.", "source_provider": "claude"}],
        [{"claim": "The change improves latency by 100%.", "source_provider": "claude"}],
    )

    assert len(items) == 2


def test_merge_items_keeps_similar_claims_from_different_sources():
    items = merge_items(
        [{"claim": "Scope should be enforced when possible.", "source_provider": "claude"}],
        [{"claim": "Scope should be enforced when possible.", "source_provider": "codex"}],
    )

    assert len(items) == 2
