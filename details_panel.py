from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
)

from delegates import DateTimeEditorWithClear
from model import PLANNED_BUCKETS, RECURRENCE_FREQUENCIES
from ui_layout import add_form_row, add_left_aligned_buttons, configure_box_layout, configure_form_layout, configure_grid_layout


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


class TaskDetailsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._task_id: int | None = None

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        self.meta = QLabel("No task selected")
        self.meta.setWordWrap(True)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta.setToolTip("Read-only summary of selected task and progress.")
        root.addWidget(self.meta)

        project_group = QGroupBox("Project intelligence")
        project_layout = QVBoxLayout(project_group)
        configure_box_layout(project_layout)
        self.project_insights = QLabel("No project insights available.")
        self.project_insights.setWordWrap(True)
        self.project_insights.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.project_insights.setToolTip("Next-action, blocked/stalled state, and related project insight.")
        project_layout.addWidget(self.project_insights)
        root.addWidget(project_group)

        editor_group = QGroupBox("Task details")
        editor_layout = QVBoxLayout(editor_group)
        configure_box_layout(editor_layout)
        form = QFormLayout()
        configure_form_layout(form, label_width=130)
        editor_layout.addLayout(form)
        root.addWidget(editor_group)

        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Task notes...")
        self.notes.setFixedHeight(120)
        self.notes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.notes.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.notes.setToolTip("Long-form notes for selected task.")
        add_form_row(form, "Notes", self.notes)

        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Comma-separated tags")
        self.tags.setToolTip("Tags for selected task, separated by commas.")
        add_form_row(form, "Tags", self.tags)

        self.bucket = QComboBox()
        self.bucket.addItems(PLANNED_BUCKETS)
        self.bucket.setToolTip("Planning bucket used by built-in perspectives.")
        add_form_row(form, "Bucket", self.bucket)

        self.waiting_for = QLineEdit()
        self.waiting_for.setPlaceholderText("Waiting for (optional)")
        self.waiting_for.setToolTip("Optional waiting context, person, or external dependency note.")
        add_form_row(form, "Waiting", self.waiting_for)

        self.depends_on = QLineEdit()
        self.depends_on.setPlaceholderText("Dependency task IDs (comma-separated)")
        self.depends_on.setToolTip("Task IDs that block this task (comma-separated).")
        add_form_row(form, "Blocked by IDs", self.depends_on)

        self.recurrence = QComboBox()
        self.recurrence.addItem("(none)")
        self.recurrence.addItems(RECURRENCE_FREQUENCIES)
        self.recurrence.setToolTip("Recurring schedule frequency.")
        add_form_row(form, "Recurrence", self.recurrence)

        self.recurrence_next_on_done = QCheckBox("Create next occurrence when done")
        self.recurrence_next_on_done.setToolTip("When enabled, next occurrence is generated after marking current task Done.")
        add_form_row(form, "", self.recurrence_next_on_done)

        self.effort_minutes = QSpinBox()
        self.effort_minutes.setRange(-1, 1_000_000)
        self.effort_minutes.setSpecialValueText("None")
        self.effort_minutes.setToolTip("Estimated effort in minutes. Use None if not estimated.")
        add_form_row(form, "Est. minutes", self.effort_minutes)

        self.actual_minutes = QSpinBox()
        self.actual_minutes.setRange(0, 1_000_000)
        self.actual_minutes.setToolTip("Actual effort in minutes.")
        add_form_row(form, "Actual minutes", self.actual_minutes)

        rem_row = QHBoxLayout()
        configure_box_layout(rem_row)
        self.reminder_at = DateTimeEditorWithClear()
        self.reminder_at.setToolTip("Reminder date/time for selected task.")
        rem_row.addWidget(self.reminder_at, 1)

        self.reminder_before_minutes = QSpinBox()
        self.reminder_before_minutes.setRange(0, 10080)
        self.reminder_before_minutes.setSuffix(" min before due")
        self.reminder_before_minutes.setToolTip("Minutes before due date for due-based reminder.")
        rem_row.addWidget(self.reminder_before_minutes)
        add_form_row(form, "Reminder", self._wrap(rem_row))

        actions_group = QGroupBox("Task actions")
        actions_layout = QGridLayout(actions_group)
        configure_grid_layout(actions_layout)
        self.save_btn = QPushButton("Save details")
        self.save_btn.setToolTip("Save edited task metadata from this panel.")
        self.start_timer_btn = QPushButton("Start timer")
        self.start_timer_btn.setToolTip("Start time tracking timer for selected task.")
        self.stop_timer_btn = QPushButton("Stop timer")
        self.stop_timer_btn.setToolTip("Stop timer and add elapsed minutes to actual time.")
        self.set_reminder_btn = QPushButton("Set reminder")
        self.set_reminder_btn.setToolTip("Store reminder using selected reminder date/time.")
        self.set_due_reminder_btn = QPushButton("Use due date")
        self.set_due_reminder_btn.setToolTip("Set reminder based on due date minus offset.")
        self.clear_reminder_btn = QPushButton("Clear reminder")
        self.clear_reminder_btn.setToolTip("Remove reminder from selected task.")
        actions_layout.addWidget(self.save_btn, 0, 0)
        actions_layout.addWidget(self.start_timer_btn, 0, 1)
        actions_layout.addWidget(self.stop_timer_btn, 0, 2)
        actions_layout.addWidget(self.set_reminder_btn, 1, 0)
        actions_layout.addWidget(self.set_due_reminder_btn, 1, 1)
        actions_layout.addWidget(self.clear_reminder_btn, 1, 2)
        actions_layout.setColumnStretch(3, 1)
        root.addWidget(actions_group)

        attachments_group = QGroupBox("Attachments")
        attachments_layout = QVBoxLayout(attachments_group)
        configure_box_layout(attachments_layout)
        self.attachments = QListWidget()
        self.attachments.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.attachments.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.attachments.setToolTip("Linked files/folders for this task.")
        attachments_layout.addWidget(self.attachments, 1)

        att_row = QHBoxLayout()
        configure_box_layout(att_row)
        self.add_file_btn = QPushButton("Add file")
        self.add_file_btn.setToolTip("Attach one or more files to selected task.")
        self.add_folder_btn = QPushButton("Add folder")
        self.add_folder_btn.setToolTip("Attach a folder path to selected task.")
        self.open_attachment_btn = QPushButton("Open")
        self.open_attachment_btn.setToolTip("Open selected attachment with system handler.")
        self.remove_attachment_btn = QPushButton("Remove")
        self.remove_attachment_btn.setToolTip("Remove selected attachment link from task.")
        add_left_aligned_buttons(
            att_row,
            self.add_file_btn,
            self.add_folder_btn,
            self.open_attachment_btn,
            self.remove_attachment_btn,
        )
        attachments_layout.addLayout(att_row)
        root.addWidget(attachments_group, 1)

    def _wrap(self, layout):
        w = QWidget()
        w.setLayout(layout)
        return w

    def task_id(self) -> int | None:
        return self._task_id

    def selected_attachment(self) -> tuple[int | None, str]:
        it = self.attachments.currentItem()
        if not it:
            return None, ""
        aid = it.data(Qt.ItemDataRole.UserRole)
        path = str(it.data(Qt.ItemDataRole.UserRole + 1) or "")
        try:
            aid = int(aid)
        except Exception:
            aid = None
        return aid, path

    def set_task_details(self, details: dict | None):
        self._task_id = int(details["id"]) if details and details.get("id") is not None else None
        if not details:
            self.meta.setText("No task selected")
            self.project_insights.setText("No project insights available.")
            self.notes.setPlainText("")
            self.tags.setText("")
            self.waiting_for.setText("")
            self.depends_on.setText("")
            self.bucket.setCurrentText("inbox")
            self.recurrence.setCurrentIndex(0)
            self.recurrence_next_on_done.setChecked(False)
            self.effort_minutes.setValue(-1)
            self.actual_minutes.setValue(0)
            self.reminder_at.set_iso_datetime(None)
            self.reminder_before_minutes.setValue(0)
            self.attachments.clear()
            return

        progress = details.get("child_progress") or {}
        prog_txt = ""
        if int(progress.get("total") or 0) > 0:
            prog_txt = f" | Child progress: {int(progress.get('done') or 0)}/{int(progress.get('total') or 0)}"

        rec = details.get("recurrence")
        rec_txt = "none"
        if rec and rec.get("frequency"):
            rec_txt = str(rec.get("frequency"))

        proj = details.get("project_summary") or {}
        proj_txt = ""
        if proj:
            proj_bits = []
            state_label = str(proj.get("state_label") or "").strip()
            if state_label:
                proj_bits.append(f"Project: {state_label}")
            next_desc = str(proj.get("next_action_description") or "").strip()
            if next_desc:
                proj_bits.append(f"Next action: {next_desc}")
            elif bool(proj.get("no_next_action")):
                proj_bits.append("Next action: none")
            blocked_children = int(proj.get("blocked_child_count") or 0)
            waiting_children = int(proj.get("waiting_child_count") or 0)
            if blocked_children > 0:
                proj_bits.append(f"Blocked children: {blocked_children}")
            if waiting_children > 0:
                proj_bits.append(f"Waiting children: {waiting_children}")
            oldest_waiting = int(proj.get("oldest_waiting_days") or 0)
            if oldest_waiting > 0:
                proj_bits.append(f"Oldest waiting: {oldest_waiting}d")
            stalled_reason = str(proj.get("stalled_reason_text") or "").strip()
            if stalled_reason:
                proj_bits.append(f"Why stalled: {stalled_reason}")
            proj_txt = "".join(f" | {part}" for part in proj_bits)

        self.meta.setText(
            f"ID {details['id']} | Status: {details.get('status', '')} | Priority: {details.get('priority', '')}"
            f"{prog_txt} | Recurrence: {rec_txt}{proj_txt}"
        )

        insight_lines: list[str] = []
        if proj:
            if state_label:
                insight_lines.append(f"State: {state_label}")
            if next_desc:
                insight_lines.append(f"Next action: {next_desc}")
            elif bool(proj.get("no_next_action")):
                insight_lines.append("Next action: none available")
            if blocked_children > 0 or waiting_children > 0:
                insight_lines.append(
                    f"Blocked children: {blocked_children} | Waiting children: {waiting_children}"
                )
            if oldest_waiting > 0:
                insight_lines.append(f"Oldest waiting child: {oldest_waiting} day(s)")
            if stalled_reason:
                insight_lines.append(f"Why stalled: {stalled_reason}")
        else:
            waiting_for = str(details.get("waiting_for") or "").strip()
            dep_count = len(details.get("dependencies") or [])
            if waiting_for:
                insight_lines.append(f"Waiting for: {waiting_for}")
            if dep_count > 0:
                insight_lines.append(f"Blocked by: {dep_count} dependency task(s)")
        self.project_insights.setText("\n".join(insight_lines) if insight_lines else "No project insights available.")

        self.notes.setPlainText(str(details.get("notes") or ""))
        self.tags.setText(", ".join(str(t) for t in (details.get("tags") or [])))
        bucket = str(details.get("planned_bucket") or "inbox").lower()
        if self.bucket.findText(bucket) >= 0:
            self.bucket.setCurrentText(bucket)
        else:
            self.bucket.setCurrentText("inbox")

        self.waiting_for.setText(str(details.get("waiting_for") or ""))

        deps = details.get("dependencies") or []
        dep_ids = [str(int(d.get("id"))) for d in deps if d.get("id") is not None]
        self.depends_on.setText(", ".join(dep_ids))

        if rec and rec.get("frequency"):
            freq = str(rec.get("frequency")).lower()
            idx = self.recurrence.findText(freq)
            self.recurrence.setCurrentIndex(idx if idx >= 0 else 0)
            self.recurrence_next_on_done.setChecked(int(rec.get("create_next_on_done") or 0) == 1)
        else:
            self.recurrence.setCurrentIndex(0)
            self.recurrence_next_on_done.setChecked(False)

        effort = details.get("effort_minutes")
        self.effort_minutes.setValue(-1 if effort is None else max(-1, _safe_int(effort, -1)))
        self.actual_minutes.setValue(max(0, _safe_int(details.get("actual_minutes"), 0)))

        reminder_at = str(details.get("reminder_at") or "").strip()
        self.reminder_at.set_iso_datetime(reminder_at if reminder_at else None)
        self.reminder_before_minutes.setValue(max(0, _safe_int(details.get("reminder_minutes_before"), 0)))

        self.attachments.clear()
        for att in details.get("attachments") or []:
            label = str(att.get("label") or "").strip()
            path = str(att.get("path") or "")
            text = f"{label} -> {path}" if label else path
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, int(att.get("id")))
            item.setData(Qt.ItemDataRole.UserRole + 1, path)
            self.attachments.addItem(item)

    def collect_payload(self) -> dict:
        tags = []
        for part in self.tags.text().split(","):
            s = part.strip()
            if s:
                tags.append(s)

        dep_ids = []
        for part in self.depends_on.text().split(","):
            s = part.strip()
            if not s:
                continue
            try:
                dep_ids.append(int(s))
            except Exception:
                continue

        recurrence_text = self.recurrence.currentText().strip().lower()
        recurrence = recurrence_text if recurrence_text in RECURRENCE_FREQUENCIES else None

        effort = int(self.effort_minutes.value())
        if effort < 0:
            effort = None

        return {
            "notes": self.notes.toPlainText(),
            "tags": tags,
            "bucket": self.bucket.currentText().strip().lower(),
            "waiting_for": self.waiting_for.text(),
            "dependencies": dep_ids,
            "recurrence": recurrence,
            "recurrence_next_on_done": self.recurrence_next_on_done.isChecked(),
            "effort_minutes": effort,
            "actual_minutes": int(self.actual_minutes.value()),
        }

    def reminder_iso(self) -> str | None:
        return self.reminder_at.iso_datetime()
