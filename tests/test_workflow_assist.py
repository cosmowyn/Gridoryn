from __future__ import annotations

from workflow_assist import (
    acknowledge_review_items,
    clear_review_acknowledgements,
    filter_acknowledged_review_data,
    review_ack_state_from_setting,
    review_ack_state_to_setting,
    should_show_onboarding,
)


def test_review_ack_roundtrip_and_filtering():
    state = acknowledge_review_items({}, "overdue", [1, 2, 2, -1])
    state = acknowledge_review_items(state, "waiting_old", [5])
    state = acknowledge_review_items(
        state,
        "overdue_milestones",
        ["milestone:10", "milestone:10", " milestone:11 "],
    )

    raw = review_ack_state_to_setting(state)
    loaded = review_ack_state_from_setting(raw)

    assert loaded == {
        "overdue": {"1", "2"},
        "waiting_old": {"5"},
        "overdue_milestones": {"milestone:10", "milestone:11"},
    }

    data = {
        "overdue": [{"id": 1}, {"id": 2}, {"id": 3}],
        "waiting_old": [{"id": 5}, {"id": 6}],
        "overdue_milestones": [
            {"id": 10, "review_key": "milestone:10"},
            {"id": 11, "review_key": "milestone:11"},
            {"id": 12, "review_key": "milestone:12"},
        ],
    }
    filtered, hidden = filter_acknowledged_review_data(data, loaded)

    assert [row["id"] for row in filtered["overdue"]] == [3]
    assert [row["id"] for row in filtered["waiting_old"]] == [6]
    assert [row["id"] for row in filtered["overdue_milestones"]] == [12]
    assert hidden == {"overdue": 2, "waiting_old": 1, "overdue_milestones": 2}


def test_clear_review_acknowledgements_and_onboarding_rule():
    state = {"overdue": {"1", "2"}, "waiting_old": {"3"}}
    assert clear_review_acknowledgements(state, category="overdue") == {"waiting_old": {"3"}}
    assert clear_review_acknowledgements(state, category=None) == {}

    assert should_show_onboarding(False, 0) is True
    assert should_show_onboarding(False, 3) is False
    assert should_show_onboarding(True, 0) is False
