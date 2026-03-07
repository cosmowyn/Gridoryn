from __future__ import annotations

from PySide6.QtCore import Qt, QDateTime
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QPushButton,
    QDateTimeEdit,
)

from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
)


class ReminderBatchDialog(QDialog):
    ACTION_NONE = "none"
    ACTION_ACK = "ack"
    ACTION_SNOOZE = "snooze"

    def __init__(self, reminders: list[dict], parent=None):
        super().__init__(parent)
        self._action = self.ACTION_NONE
        self.setWindowTitle("Task reminders")
        self.setModal(True)
        self.resize(560, 360)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        title = QLabel(f"{len(reminders)} reminder(s) are due")
        title.setWordWrap(True)
        root.addWidget(title)

        self.list = QListWidget()
        self.list.setToolTip("Due reminders grouped by time.")
        for row in reminders:
            desc = str(row.get("description") or "(no description)")
            due = str(row.get("due_date") or "(no due date)")
            rem = str(row.get("reminder_at") or "")
            prio = row.get("priority")
            text = f"[P{prio}] {desc} | Reminder: {rem} | Due: {due}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
            self.list.addItem(it)
        root.addWidget(self.list, 1)

        row = QFormLayout()
        configure_form_layout(row, label_width=100)
        self.snooze_at = QDateTimeEdit()
        self.snooze_at.setCalendarPopup(True)
        self.snooze_at.setDisplayFormat("dd-MMM-yyyy HH:mm")
        self.snooze_at.setDateTime(QDateTime.currentDateTime().addSecs(15 * 60))
        self.snooze_at.setToolTip("Date and time to show these reminders again.")
        add_form_row(row, "Snooze until", self.snooze_at)
        root.addLayout(row)

        btn_row = QHBoxLayout()
        self.ack_btn = QPushButton("Acknowledge all")
        self.ack_btn.setToolTip("Mark shown reminders as acknowledged so they do not reappear.")
        self.snooze_btn = QPushButton("Snooze all")
        self.snooze_btn.setToolTip("Move shown reminders to the selected snooze date/time.")
        self.close_btn = QPushButton("Close")
        self.close_btn.setToolTip("Close without changing reminder state.")
        add_left_aligned_buttons(btn_row, self.ack_btn, self.snooze_btn, self.close_btn)
        root.addLayout(btn_row)

        self.ack_btn.clicked.connect(self._acknowledge)
        self.snooze_btn.clicked.connect(self._snooze)
        self.close_btn.clicked.connect(self.reject)

    def _acknowledge(self):
        self._action = self.ACTION_ACK
        self.accept()

    def _snooze(self):
        self._action = self.ACTION_SNOOZE
        self.accept()

    def action(self) -> str:
        return self._action

    def snooze_iso(self) -> str:
        return self.snooze_at.dateTime().toString("yyyy-MM-dd HH:mm:ss")
