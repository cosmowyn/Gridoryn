from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from capture_parsing import (
    BulkPostponeOverdueIntent,
    CaptureIntent,
    CreateRecurringTaskIntent,
    RescheduleSelectedIntent,
    ShowSearchIntent,
    TaskCaptureIntent,
)


@dataclass
class CaptureExecutionResult:
    success: bool
    message: str = ""


class CaptureActionHandler(Protocol):
    def handle_task_capture(self, intent: TaskCaptureIntent, default_bucket: str) -> CaptureExecutionResult: ...
    def handle_reschedule_selected(self, intent: RescheduleSelectedIntent) -> CaptureExecutionResult: ...
    def handle_bulk_postpone_overdue(self, intent: BulkPostponeOverdueIntent) -> CaptureExecutionResult: ...
    def handle_show_search(self, intent: ShowSearchIntent) -> CaptureExecutionResult: ...
    def handle_create_recurring(self, intent: CreateRecurringTaskIntent, default_bucket: str) -> CaptureExecutionResult: ...


def execute_capture_intent(
    intent: CaptureIntent,
    handler: CaptureActionHandler,
    *,
    default_bucket: str = "inbox",
) -> CaptureExecutionResult:
    if isinstance(intent, TaskCaptureIntent):
        return handler.handle_task_capture(intent, default_bucket)
    if isinstance(intent, RescheduleSelectedIntent):
        return handler.handle_reschedule_selected(intent)
    if isinstance(intent, BulkPostponeOverdueIntent):
        return handler.handle_bulk_postpone_overdue(intent)
    if isinstance(intent, ShowSearchIntent):
        return handler.handle_show_search(intent)
    if isinstance(intent, CreateRecurringTaskIntent):
        return handler.handle_create_recurring(intent, default_bucket)
    return CaptureExecutionResult(False, "Unsupported capture intent.")
