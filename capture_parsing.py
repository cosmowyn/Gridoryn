from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Union

from query_parsing import QuickAddResult, parse_quick_add


WEEKDAY_TO_INT = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass
class TaskCaptureIntent:
    kind: str
    parsed: QuickAddResult


@dataclass
class RescheduleSelectedIntent:
    kind: str
    due_date: str


@dataclass
class BulkPostponeOverdueIntent:
    kind: str
    days: int
    tag: str | None = None


@dataclass
class ShowSearchIntent:
    kind: str
    query_text: str
    perspective: str | None = None


@dataclass
class CreateRecurringTaskIntent:
    kind: str
    parsed: QuickAddResult
    frequency: str
    due_date: str
    reminder_at: str | None = None
    create_next_on_done: bool = True


CaptureIntent = Union[
    TaskCaptureIntent,
    RescheduleSelectedIntent,
    BulkPostponeOverdueIntent,
    ShowSearchIntent,
    CreateRecurringTaskIntent,
]


def _today() -> date:
    return date.today()


def _normalize_time(text: str | None) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in ("%H:%M", "%H.%M"):
        try:
            parsed = datetime.strptime(raw, fmt).time()
            return parsed.strftime("%H:%M:%S")
        except Exception:
            continue
    return None


def _resolve_due_phrase(text: str) -> str | None:
    parsed = parse_quick_add(f"capture {str(text or '').strip()}")
    return parsed.due_date


def _next_weekday_occurrence(weekday_name: str, today: date | None = None) -> date | None:
    wd = WEEKDAY_TO_INT.get(str(weekday_name or "").strip().lower())
    if wd is None:
        return None
    current = today or _today()
    delta = (wd - current.weekday()) % 7
    return current + timedelta(days=delta)


def parse_capture_input(text: str) -> CaptureIntent:
    raw = str(text or "").strip()
    if not raw:
        return TaskCaptureIntent(kind="task", parsed=parse_quick_add(raw))

    move_match = re.fullmatch(r"move\s+(?:this|selected(?:\s+task)?)\s+to\s+(.+)", raw, flags=re.IGNORECASE)
    if move_match:
        due_date = _resolve_due_phrase(move_match.group(1))
        if due_date:
            return RescheduleSelectedIntent(kind="reschedule_selected", due_date=due_date)

    postpone_match = re.fullmatch(
        r"postpone\s+all\s+overdue(?:\s+([@#]?[a-zA-Z0-9_-]+))?\s+tasks?\s+by\s+([+-]?\d+)\s+days?",
        raw,
        flags=re.IGNORECASE,
    )
    if postpone_match:
        tag = str(postpone_match.group(1) or "").strip()
        if tag.startswith("@") or tag.startswith("#"):
            tag = tag[1:]
        tag = tag or None
        try:
            days = int(postpone_match.group(2))
        except Exception:
            days = 0
        if days != 0:
            return BulkPostponeOverdueIntent(kind="bulk_postpone_overdue", days=days, tag=tag)

    show_blocked_match = re.fullmatch(r"show\s+blocked\s+tasks?", raw, flags=re.IGNORECASE)
    if show_blocked_match:
        return ShowSearchIntent(kind="show_search", query_text="is:blocked", perspective="all")

    show_waiting_match = re.fullmatch(r"show\s+waiting\s+tasks?", raw, flags=re.IGNORECASE)
    if show_waiting_match:
        return ShowSearchIntent(kind="show_search", query_text="is:waiting", perspective="all")

    recurring_match = re.fullmatch(
        r"create\s+(.+?)\s+every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at\s+([0-9]{1,2}[:.][0-9]{2}))?",
        raw,
        flags=re.IGNORECASE,
    )
    if recurring_match:
        description_part = str(recurring_match.group(1) or "").strip()
        weekday_name = str(recurring_match.group(2) or "").strip().lower()
        reminder_time = _normalize_time(recurring_match.group(3))
        due = _next_weekday_occurrence(weekday_name)
        if due is not None:
            parsed = parse_quick_add(description_part)
            if not parsed.description:
                parsed.description = description_part
            if parsed.bucket is None:
                parsed.bucket = "upcoming" if due > _today() else "today"
            reminder_at = None
            if reminder_time:
                reminder_at = f"{due.isoformat()} {reminder_time}"
            return CreateRecurringTaskIntent(
                kind="create_recurring",
                parsed=parsed,
                frequency="weekly",
                due_date=due.isoformat(),
                reminder_at=reminder_at,
                create_next_on_done=True,
            )

    return TaskCaptureIntent(kind="task", parsed=parse_quick_add(raw))
