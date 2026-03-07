from __future__ import annotations

from template_params import apply_template_values, collect_template_placeholders


def test_template_placeholders_and_due_normalization():
    payload = {
        "tasks": [
            {
                "description": "Follow up with {owner}",
                "due_date": "{due_date}",
                "custom": {"Owner": "{owner}"},
            }
        ]
    }

    placeholders = collect_template_placeholders(payload)
    resolved = apply_template_values(payload, {"owner": "Alex", "due_date": "next week"})

    assert placeholders == ["due_date", "owner"]
    assert resolved["tasks"][0]["description"] == "Follow up with Alex"
    assert resolved["tasks"][0]["custom"]["Owner"] == "Alex"
    assert isinstance(resolved["tasks"][0]["due_date"], str)
    assert len(resolved["tasks"][0]["due_date"]) == 10
