from __future__ import annotations

from capture_actions import CaptureExecutionResult, execute_capture_intent
from capture_parsing import (
    BulkPostponeOverdueIntent,
    CreateRecurringTaskIntent,
    RescheduleSelectedIntent,
    ShowSearchIntent,
    TaskCaptureIntent,
    parse_capture_input,
)


class _StubHandler:
    def __init__(self):
        self.calls: list[tuple[str, object, str | None]] = []

    def handle_task_capture(self, intent, default_bucket: str):
        self.calls.append(("task", intent, default_bucket))
        return CaptureExecutionResult(True, "task")

    def handle_reschedule_selected(self, intent):
        self.calls.append(("move", intent, None))
        return CaptureExecutionResult(True, "move")

    def handle_bulk_postpone_overdue(self, intent):
        self.calls.append(("bulk", intent, None))
        return CaptureExecutionResult(True, "bulk")

    def handle_show_search(self, intent):
        self.calls.append(("show", intent, None))
        return CaptureExecutionResult(True, "show")

    def handle_create_recurring(self, intent, default_bucket: str):
        self.calls.append(("recurring", intent, default_bucket))
        return CaptureExecutionResult(True, "recurring")


def test_parse_task_capture_with_inline_directives():
    intent = parse_capture_input("Call supplier @work #urgent !p1 /today +child")

    assert isinstance(intent, TaskCaptureIntent)
    assert intent.parsed.description == "Call supplier"
    assert intent.parsed.priority == 1
    assert intent.parsed.bucket == "today"
    assert intent.parsed.create_as_child is True
    assert intent.parsed.tags == ["work", "urgent"]


def test_parse_move_selected_command():
    intent = parse_capture_input("move this to next friday")

    assert isinstance(intent, RescheduleSelectedIntent)
    assert intent.due_date


def test_parse_bulk_postpone_and_show_blocked_commands():
    postpone = parse_capture_input("postpone all overdue work tasks by 2 days")
    show = parse_capture_input("show blocked tasks")

    assert isinstance(postpone, BulkPostponeOverdueIntent)
    assert postpone.days == 2
    assert postpone.tag == "work"

    assert isinstance(show, ShowSearchIntent)
    assert show.query_text == "is:blocked"
    assert show.perspective == "all"


def test_parse_create_recurring_weekly_review():
    intent = parse_capture_input("create weekly review @ops every friday at 16:00")

    assert isinstance(intent, CreateRecurringTaskIntent)
    assert intent.frequency == "weekly"
    assert intent.parsed.description == "weekly review"
    assert intent.parsed.tags == ["ops"]
    assert intent.reminder_at is not None
    assert intent.due_date in intent.reminder_at


def test_execute_capture_intent_routes_to_expected_handler():
    handler = _StubHandler()

    result = execute_capture_intent(parse_capture_input("show blocked tasks"), handler, default_bucket="inbox")
    assert result.success is True
    assert handler.calls[-1][0] == "show"

    result = execute_capture_intent(parse_capture_input("create weekly review every friday at 16:00"), handler, default_bucket="inbox")
    assert result.success is True
    assert handler.calls[-1][0] == "recurring"
    assert handler.calls[-1][2] == "inbox"

    result = execute_capture_intent(parse_capture_input("Inbox item @home"), handler, default_bucket="inbox")
    assert result.success is True
    assert handler.calls[-1][0] == "task"
    assert handler.calls[-1][2] == "inbox"
