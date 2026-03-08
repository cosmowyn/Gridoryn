from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from context_help import attach_context_help
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
)


REVIEW_CATEGORIES: list[tuple[str, str]] = [
    ("overdue", "Overdue"),
    ("overdue_milestones", "Overdue Milestones"),
    ("deliverables_due_soon", "Deliverables Due Soon"),
    ("high_risk_registers", "High-Severity Risks"),
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

PM_REVIEW_CATEGORIES = {
    "overdue_milestones",
    "deliverables_due_soon",
    "high_risk_registers",
}


class ReviewWorkflowPanel(QWidget):
    refreshRequested = Signal(int, int, int)  # waiting_days, stalled_days, recent_days
    focusTaskRequested = Signal(int)
    markDoneRequested = Signal(list)
    archiveRequested = Signal(list)
    restoreRequested = Signal(list)
    acknowledgeRequested = Signal(str, list)
    clearAcknowledgedRequested = Signal(str)
    useCategoryRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._lists: dict[str, QListWidget] = {}

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        controls_panel = SectionPanel(
            "Review workflow",
            "Thresholds stay close to the refresh action so the review flow "
            "is easy to re-run during a cleanup pass.",
        )
        controls_panel.setToolTip(
            "Suggested flow: Inbox -> Overdue -> Milestones / Deliverables "
            "-> No Due Date -> Projects -> Waiting -> Archive."
        )
        self.help_btn = attach_context_help(
            controls_panel,
            "review_panel",
            self,
            tooltip="Open help for the review workflow",
        )
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
        controls_panel.body_layout.addLayout(controls)

        self.review_summary = QLabel("Visible items: 0. Hidden handled items: 0.")
        self.review_summary.setWordWrap(True)
        self.review_summary.setToolTip(
            "Compact review summary for visible items and acknowledged items "
            "currently hidden from this pass."
        )
        controls_panel.body_layout.addWidget(self.review_summary)

        self.refresh_btn = QPushButton("Refresh review")
        self.refresh_btn.setToolTip("Refresh all review categories using current thresholds.")
        controls_actions = QHBoxLayout()
        add_left_aligned_buttons(controls_actions, self.refresh_btn)
        controls_panel.body_layout.addLayout(controls_actions)
        root.addWidget(controls_panel)

        content_panel = SectionPanel(
            "Review categories",
            "Actions stay attached to the category view instead of floating "
            "below the full dock.",
        )
        root.addWidget(content_panel, 1)

        actions = QHBoxLayout()
        self.focus_btn = QPushButton("Focus")
        self.focus_btn.setToolTip("Jump to the selected review item in the main tree.")
        self.use_btn = QPushButton("Use in tree")
        self.use_btn.setToolTip("Apply a best-effort main-tree view for the current review category.")
        self.ack_btn = QPushButton("Acknowledge")
        self.ack_btn.setToolTip("Hide the selected review items from this category until cleared.")
        self.done_btn = QPushButton("Mark done")
        self.done_btn.setToolTip("Mark the selected review items as Done.")
        self.archive_btn = QPushButton("Archive")
        self.archive_btn.setToolTip("Archive the selected review items.")
        self.restore_btn = QPushButton("Restore")
        self.restore_btn.setToolTip("Restore the selected archived review items.")
        self.clear_ack_btn = QPushButton("Clear handled")
        self.clear_ack_btn.setToolTip("Show previously acknowledged items again for the current category.")
        add_left_aligned_buttons(
            actions,
            self.focus_btn,
            self.use_btn,
            self.ack_btn,
            self.done_btn,
            self.archive_btn,
            self.restore_btn,
            self.clear_ack_btn,
        )
        content_panel.body_layout.addLayout(actions)

        self.tabs = QTabWidget()
        content_panel.body_layout.addWidget(self.tabs, 1)

        for key, label in REVIEW_CATEGORIES:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            configure_box_layout(page_layout)
            lw = QListWidget()
            lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            lw.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lw.setToolTip(f"{label} review items. Double-click to focus.")
            lw.itemDoubleClicked.connect(self._on_item_activated)
            lw.itemSelectionChanged.connect(self._update_action_states)
            stack = EmptyStateStack(
                lw,
                f"No {label.lower()} right now.",
                "Refresh review or adjust the thresholds to repopulate this category.",
            )
            page._stack = stack  # type: ignore[attr-defined]
            page_layout.addWidget(stack, 1)
            self.tabs.addTab(page, label)
            self._lists[key] = lw

        self.refresh_btn.clicked.connect(self._emit_refresh)
        self.focus_btn.clicked.connect(self._emit_focus)
        self.use_btn.clicked.connect(lambda: self.useCategoryRequested.emit(self.current_category()))
        self.ack_btn.clicked.connect(
            lambda: self.acknowledgeRequested.emit(
                self.current_category(),
                self.selected_review_keys(),
            )
        )
        self.done_btn.clicked.connect(lambda: self.markDoneRequested.emit(self.selected_task_ids()))
        self.archive_btn.clicked.connect(lambda: self.archiveRequested.emit(self.selected_task_ids()))
        self.restore_btn.clicked.connect(lambda: self.restoreRequested.emit(self.selected_task_ids()))
        self.clear_ack_btn.clicked.connect(lambda: self.clearAcknowledgedRequested.emit(self.current_category()))
        self.tabs.currentChanged.connect(lambda _index: self._update_action_states())
        self._update_action_states()

    def sizeHint(self) -> QSize:
        return QSize(560, 620)

    def minimumSizeHint(self) -> QSize:
        return QSize(380, 460)

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
        if isinstance(w, QListWidget):
            return w
        if isinstance(w, QWidget):
            for lst in self._lists.values():
                if lst.parentWidget() is not None and lst.parentWidget().parentWidget() is w:
                    return lst
        return None

    def current_category(self) -> str:
        idx = self.tabs.currentIndex()
        if idx < 0 or idx >= len(REVIEW_CATEGORIES):
            return REVIEW_CATEGORIES[0][0]
        return str(REVIEW_CATEGORIES[idx][0])

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

    def selected_review_keys(self) -> list[str]:
        lw = self._current_list()
        if lw is None:
            return []
        keys: list[str] = []
        seen: set[str] = set()
        for it in lw.selectedItems():
            raw = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
            if not raw or raw in seen:
                continue
            seen.add(raw)
            keys.append(raw)
        return keys

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

    def _update_action_states(self):
        category = self.current_category()
        task_ids = self.selected_task_ids()
        can_focus = bool(task_ids)
        is_pm_category = category in PM_REVIEW_CATEGORIES
        self.focus_btn.setEnabled(can_focus)
        self.use_btn.setEnabled(True)
        self.ack_btn.setEnabled(bool(self.selected_review_keys()))
        self.clear_ack_btn.setEnabled(True)
        self.done_btn.setEnabled(bool(task_ids) and not is_pm_category)
        self.archive_btn.setEnabled(bool(task_ids) and not is_pm_category)
        self.restore_btn.setEnabled(bool(task_ids) and not is_pm_category)

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

    def set_review_data(self, data: dict[str, list[dict]], hidden_counts: dict[str, int] | None = None):
        payload = data or {}
        hidden_map = hidden_counts or {}
        total_visible = 0
        total_hidden = 0
        for key, label in REVIEW_CATEGORIES:
            lw = self._lists.get(key)
            if lw is None:
                continue
            rows = payload.get(key) or []
            hidden = int(hidden_map.get(key) or 0)
            total_visible += len(rows)
            total_hidden += hidden
            lw.clear()
            for row in rows:
                item = QListWidgetItem(self._format_item_text(row))
                focus_id = int(row.get("review_focus_id") or row.get("id") or 0)
                item.setData(Qt.ItemDataRole.UserRole, focus_id)
                item.setData(
                    Qt.ItemDataRole.UserRole + 1,
                    str(row.get("review_key") or row.get("id") or "").strip(),
                )
                lw.addItem(item)
            parent_page = lw.parentWidget().parentWidget() if lw.parentWidget() is not None else None
            tab_idx = self.tabs.indexOf(parent_page) if isinstance(parent_page, QWidget) else -1
            if tab_idx >= 0:
                self.tabs.setTabText(tab_idx, f"{label} ({len(rows)})")
            stack = getattr(parent_page, "_stack", None)
            if isinstance(stack, EmptyStateStack):
                stack.set_has_content(bool(rows))
        self.review_summary.setText(
            f"Visible items: {total_visible}. Hidden handled items: {total_hidden}."
        )
        self._update_action_states()
