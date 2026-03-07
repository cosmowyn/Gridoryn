from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui_layout import add_form_row, add_left_aligned_buttons, configure_box_layout, configure_form_layout


REVIEW_CATEGORIES: list[tuple[str, str]] = [
    ("overdue", "Overdue"),
    ("no_due", "No Due Date"),
    ("inbox_unprocessed", "Inbox Unprocessed"),
    ("stalled_projects", "Stalled Projects"),
    ("projects_no_next", "Projects: No Next Action"),
    ("blocked_projects", "Projects: Blocked"),
    ("waiting_old", "Waiting Older"),
    ("recurring_attention", "Recurring Attention"),
    ("recent_done_archived", "Recent Done/Archived"),
    ("archive_roots", "Archive Roots"),
]


class ReviewWorkflowPanel(QWidget):
    refreshRequested = Signal(int, int, int)  # waiting_days, stalled_days, recent_days
    focusTaskRequested = Signal(int)
    markDoneRequested = Signal(list)
    archiveRequested = Signal(list)
    restoreRequested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._lists: dict[str, QListWidget] = {}

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        controls_group = QGroupBox("Review controls")
        controls_root = QVBoxLayout(controls_group)
        configure_box_layout(controls_root)
        controls = QFormLayout()
        configure_form_layout(controls, label_width=160)
        self.waiting_days = QSpinBox()
        self.waiting_days.setRange(1, 365)
        self.waiting_days.setValue(7)
        self.waiting_days.setSuffix(" days")
        add_form_row(controls, "Waiting older than", self.waiting_days)

        self.stalled_days = QSpinBox()
        self.stalled_days.setRange(1, 365)
        self.stalled_days.setValue(14)
        self.stalled_days.setSuffix(" days")
        add_form_row(controls, "Stalled threshold", self.stalled_days)

        self.recent_days = QSpinBox()
        self.recent_days.setRange(1, 365)
        self.recent_days.setValue(30)
        self.recent_days.setSuffix(" days")
        add_form_row(controls, "Recent window", self.recent_days)
        controls_root.addLayout(controls)

        self.refresh_btn = QPushButton("Refresh review")
        self.refresh_btn.setToolTip("Refresh all review categories using current thresholds.")
        controls_actions = QHBoxLayout()
        add_left_aligned_buttons(controls_actions, self.refresh_btn)
        controls_root.addLayout(controls_actions)
        root.addWidget(controls_group)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        for key, label in REVIEW_CATEGORIES:
            lw = QListWidget()
            lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            lw.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lw.setToolTip(f"{label} tasks. Double-click to focus.")
            lw.itemDoubleClicked.connect(self._on_item_activated)
            self.tabs.addTab(lw, label)
            self._lists[key] = lw

        actions = QHBoxLayout()
        self.focus_btn = QPushButton("Focus")
        self.done_btn = QPushButton("Mark done")
        self.archive_btn = QPushButton("Archive")
        self.restore_btn = QPushButton("Restore")
        add_left_aligned_buttons(actions, self.focus_btn, self.done_btn, self.archive_btn, self.restore_btn)
        root.addLayout(actions)

        self.refresh_btn.clicked.connect(self._emit_refresh)
        self.focus_btn.clicked.connect(self._emit_focus)
        self.done_btn.clicked.connect(lambda: self.markDoneRequested.emit(self.selected_task_ids()))
        self.archive_btn.clicked.connect(lambda: self.archiveRequested.emit(self.selected_task_ids()))
        self.restore_btn.clicked.connect(lambda: self.restoreRequested.emit(self.selected_task_ids()))

    def _emit_refresh(self):
        self.refreshRequested.emit(
            int(self.waiting_days.value()),
            int(self.stalled_days.value()),
            int(self.recent_days.value()),
        )

    def _current_list(self) -> QListWidget | None:
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None
        w = self.tabs.widget(idx)
        return w if isinstance(w, QListWidget) else None

    def selected_task_ids(self) -> list[int]:
        lw = self._current_list()
        if lw is None:
            return []
        ids = []
        seen = set()
        for it in lw.selectedItems():
            tid = it.data(Qt.ItemDataRole.UserRole)
            try:
                val = int(tid)
            except Exception:
                continue
            if val <= 0 or val in seen:
                continue
            seen.add(val)
            ids.append(val)
        return ids

    def _on_item_activated(self, item: QListWidgetItem):
        if item is None:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        try:
            tid = int(tid)
        except Exception:
            return
        if tid > 0:
            self.focusTaskRequested.emit(tid)

    def _emit_focus(self):
        ids = self.selected_task_ids()
        if ids:
            self.focusTaskRequested.emit(int(ids[0]))

    def _format_item_text(self, row: dict) -> str:
        desc = str(row.get("description") or "")
        due = str(row.get("due_date") or "-")
        status = str(row.get("status") or "")
        prio = str(row.get("priority") or "")
        extra = str(row.get("review_note") or "")
        base = f"[P{prio}] {desc} | {status} | due: {due}"
        if extra:
            return f"{base} | {extra}"
        return base

    def set_review_data(self, data: dict[str, list[dict]]):
        payload = data or {}
        for key, label in REVIEW_CATEGORIES:
            lw = self._lists.get(key)
            if lw is None:
                continue
            rows = payload.get(key) or []
            lw.clear()
            for row in rows:
                item = QListWidgetItem(self._format_item_text(row))
                item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
                lw.addItem(item)
            tab_idx = self.tabs.indexOf(lw)
            if tab_idx >= 0:
                self.tabs.setTabText(tab_idx, f"{label} ({len(rows)})")
