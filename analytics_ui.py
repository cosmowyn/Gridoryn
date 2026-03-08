from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QGridLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    SummaryCard,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
)


class AnalyticsPanel(QWidget):
    refreshRequested = Signal(int, int)  # trend_days, tag_days

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        controls_panel = SectionPanel(
            "Analytics controls",
            "Adjust analysis windows and refresh the local dashboard without "
            "leaving the current workspace.",
        )
        controls = QFormLayout()
        configure_form_layout(controls, label_width=150)
        self.trend_days = QSpinBox()
        self.trend_days.setRange(3, 90)
        self.trend_days.setValue(14)
        self.trend_days.setSuffix(" days")
        add_form_row(controls, "Trend window", self.trend_days)

        self.tag_days = QSpinBox()
        self.tag_days.setRange(7, 180)
        self.tag_days.setValue(30)
        self.tag_days.setSuffix(" days")
        add_form_row(controls, "Top tags window", self.tag_days)
        controls_panel.body_layout.addLayout(controls)

        self.refresh_btn = QPushButton("Refresh analytics")
        self.refresh_btn.setToolTip("Refresh dashboard metrics and trend summaries.")
        controls_actions = QHBoxLayout()
        add_left_aligned_buttons(controls_actions, self.refresh_btn)
        controls_panel.body_layout.addLayout(controls_actions)
        root.addWidget(controls_panel)

        summary_panel = SectionPanel(
            "Summary",
            "Key signals stay compact so the lists below can use the remaining "
            "screen space.",
        )
        summary_grid = QGridLayout()
        configure_box_layout(summary_grid, spacing=8)
        self.card_completed_today = SummaryCard("Completed today")
        self.card_completed_week = SummaryCard("Completed this week")
        self.card_overdue = SummaryCard("Overdue open")
        self.card_no_due = SummaryCard("Open with no due date")
        self.card_inbox = SummaryCard("Inbox unprocessed")
        self.card_active_archived = SummaryCard("Active open / Archived")
        self.card_projects = SummaryCard("Projects stalled / blocked / no-next")
        cards = [
            self.card_completed_today,
            self.card_completed_week,
            self.card_overdue,
            self.card_no_due,
            self.card_inbox,
            self.card_active_archived,
            self.card_projects,
        ]
        for index, card in enumerate(cards):
            summary_grid.addWidget(card, index // 3, index % 3)
        summary_panel.body_layout.addLayout(summary_grid)
        root.addWidget(summary_panel)

        top_split = QSplitter()
        top_split.setChildrenCollapsible(False)
        root.addWidget(top_split, 1)

        trend_panel = SectionPanel(
            "Completion trend",
            "Daily completions for the selected analysis window.",
        )
        self.trend_list = QListWidget()
        self.trend_list.setToolTip("Completion trend per day.")
        self.trend_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.trend_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.trend_stack = EmptyStateStack(
            self.trend_list,
            "No completion trend data.",
            "Complete tasks to populate a recent completion trend.",
        )
        trend_panel.body_layout.addWidget(self.trend_stack, 1)
        top_split.addWidget(trend_panel)

        tags_panel = SectionPanel(
            "Top tags",
            "Recent tag activity among completed work.",
        )
        self.tags_list = QListWidget()
        self.tags_list.setToolTip("Most active tags among recent completions.")
        self.tags_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tags_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tags_stack = EmptyStateStack(
            self.tags_list,
            "No tag activity yet.",
            "Complete tagged work to surface the most active tags.",
        )
        tags_panel.body_layout.addWidget(self.tags_stack, 1)
        top_split.addWidget(tags_panel)

        bottom_split = QSplitter()
        bottom_split.setChildrenCollapsible(False)
        root.addWidget(bottom_split, 1)

        workload_panel = SectionPanel(
            "Workload warnings",
            "Due-date clustering and overdue growth warnings stay attached to "
            "their own data list.",
        )
        self.workload_list = QListWidget()
        self.workload_list.setToolTip("Lightweight workload warnings based on due-date clustering and overdue growth.")
        self.workload_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.workload_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.workload_stack = EmptyStateStack(
            self.workload_list,
            "No workload warnings.",
            "The current task load looks balanced for the selected window.",
        )
        workload_panel.body_layout.addWidget(self.workload_stack, 1)
        bottom_split.addWidget(workload_panel)

        hints_panel = SectionPanel(
            "Scheduling hints",
            "Optional suggestions stay separate from hard warnings.",
        )
        self.hints_list = QListWidget()
        self.hints_list.setToolTip("Optional planning hints. These never modify tasks automatically.")
        self.hints_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hints_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hints_stack = EmptyStateStack(
            self.hints_list,
            "No scheduling hints.",
            "Optional planning hints appear when the workload logic suggests "
            "safer scheduling choices.",
        )
        hints_panel.body_layout.addWidget(self.hints_stack, 1)
        bottom_split.addWidget(hints_panel)

        self.refresh_btn.clicked.connect(self._emit_refresh)

    def sizeHint(self) -> QSize:
        return QSize(520, 560)

    def minimumSizeHint(self) -> QSize:
        return QSize(380, 420)

    def _emit_refresh(self):
        self.refreshRequested.emit(int(self.trend_days.value()), int(self.tag_days.value()))

    def set_analytics_data(self, data: dict):
        payload = data or {}

        self.card_completed_today.set_value(str(int(payload.get("completed_today") or 0)))
        self.card_completed_week.set_value(str(int(payload.get("completed_this_week") or 0)))
        self.card_overdue.set_value(str(int(payload.get("overdue_open") or 0)))
        self.card_no_due.set_value(str(int(payload.get("open_no_due") or 0)))
        self.card_inbox.set_value(str(int(payload.get("inbox_unprocessed") or 0)))
        self.card_active_archived.set_value(
            f"{int(payload.get('active_open') or 0)} / "
            f"{int(payload.get('archived_count') or 0)}"
        )
        self.card_projects.set_value(
            f"{int(payload.get('project_stalled') or 0)} / "
            f"{int(payload.get('project_blocked') or 0)} / "
            f"{int(payload.get('project_no_next') or 0)}",
            "stalled / blocked / no-next",
        )

        self.trend_list.clear()
        for row in payload.get("trend") or []:
            day = str(row.get("date") or "")
            count = int(row.get("count") or 0)
            self.trend_list.addItem(QListWidgetItem(f"{day}: {count} completed"))
        self.trend_stack.set_has_content(self.trend_list.count() > 0)

        self.tags_list.clear()
        for row in payload.get("top_tags") or []:
            tag = str(row.get("tag") or "")
            count = int(row.get("count") or 0)
            self.tags_list.addItem(QListWidgetItem(f"{tag}: {count}"))
        self.tags_stack.set_has_content(self.tags_list.count() > 0)

        self.workload_list.clear()
        busiest = payload.get("workload_busiest_days") or []
        warnings = payload.get("workload_warnings") or []
        for row in busiest:
            due = str(row.get("due_date") or "")
            total = int(row.get("task_count") or 0)
            urgent = int(row.get("high_priority_count") or 0)
            self.workload_list.addItem(QListWidgetItem(f"{due}: {total} due ({urgent} high priority)"))
        for row in warnings:
            self.workload_list.addItem(QListWidgetItem(str(row.get("message") or "")))
        self.workload_stack.set_has_content(self.workload_list.count() > 0)

        self.hints_list.clear()
        for row in payload.get("scheduling_hints") or []:
            self.hints_list.addItem(QListWidgetItem(str(row.get("message") or "")))
        self.hints_stack.set_has_content(self.hints_list.count() > 0)
