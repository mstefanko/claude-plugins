import json

import pytest

from bakeoff.work_order import ValidationError, load_work_order, strip_jsonc_comments


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
