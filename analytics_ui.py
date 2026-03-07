from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui_layout import add_form_row, add_left_aligned_buttons, configure_box_layout, configure_form_layout


class AnalyticsPanel(QWidget):
    refreshRequested = Signal(int, int)  # trend_days, tag_days

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        controls_group = QGroupBox("Analytics controls")
        controls_root = QVBoxLayout(controls_group)
        configure_box_layout(controls_root)
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
        controls_root.addLayout(controls)

        self.refresh_btn = QPushButton("Refresh analytics")
        self.refresh_btn.setToolTip("Refresh dashboard metrics and trend summaries.")
        controls_actions = QHBoxLayout()
        add_left_aligned_buttons(controls_actions, self.refresh_btn)
        controls_root.addLayout(controls_actions)
        root.addWidget(controls_group)

        metrics_group = QGroupBox("Summary")
        metrics_form = QFormLayout(metrics_group)
        configure_form_layout(metrics_form, label_width=200)
        self.lbl_completed_today = QLabel("0")
        self.lbl_completed_week = QLabel("0")
        self.lbl_overdue = QLabel("0")
        self.lbl_no_due = QLabel("0")
        self.lbl_inbox = QLabel("0")
        self.lbl_active_archived = QLabel("0 / 0")
        self.lbl_projects = QLabel("0")
        add_form_row(metrics_form, "Completed today", self.lbl_completed_today)
        add_form_row(metrics_form, "Completed this week", self.lbl_completed_week)
        add_form_row(metrics_form, "Overdue open", self.lbl_overdue)
        add_form_row(metrics_form, "Open with no due date", self.lbl_no_due)
        add_form_row(metrics_form, "Inbox unprocessed", self.lbl_inbox)
        add_form_row(metrics_form, "Active open / Archived", self.lbl_active_archived)
        add_form_row(metrics_form, "Projects stalled/blocked/no-next", self.lbl_projects)
        root.addWidget(metrics_group)

        lists = QHBoxLayout()
        configure_box_layout(lists)
        trend_group = QGroupBox("Completion trend")
        trend_layout = QVBoxLayout(trend_group)
        configure_box_layout(trend_layout)
        self.trend_list = QListWidget()
        self.trend_list.setToolTip("Completion trend per day.")
        self.trend_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.trend_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        trend_layout.addWidget(self.trend_list)

        tags_group = QGroupBox("Top tags")
        tags_layout = QVBoxLayout(tags_group)
        configure_box_layout(tags_layout)
        self.tags_list = QListWidget()
        self.tags_list.setToolTip("Most active tags among recent completions.")
        self.tags_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tags_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tags_layout.addWidget(self.tags_list)
        lists.addWidget(trend_group, 1)
        lists.addWidget(tags_group, 1)
        root.addLayout(lists, 1)

        insight_lists = QHBoxLayout()
        configure_box_layout(insight_lists)
        workload_group = QGroupBox("Workload warnings")
        workload_layout = QVBoxLayout(workload_group)
        configure_box_layout(workload_layout)
        self.workload_list = QListWidget()
        self.workload_list.setToolTip("Lightweight workload warnings based on due-date clustering and overdue growth.")
        self.workload_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.workload_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        workload_layout.addWidget(self.workload_list)

        hints_group = QGroupBox("Scheduling hints")
        hints_layout = QVBoxLayout(hints_group)
        configure_box_layout(hints_layout)
        self.hints_list = QListWidget()
        self.hints_list.setToolTip("Optional planning hints. These never modify tasks automatically.")
        self.hints_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hints_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        hints_layout.addWidget(self.hints_list)

        insight_lists.addWidget(workload_group, 1)
        insight_lists.addWidget(hints_group, 1)
        root.addLayout(insight_lists, 1)

        self.refresh_btn.clicked.connect(self._emit_refresh)

    def _emit_refresh(self):
        self.refreshRequested.emit(int(self.trend_days.value()), int(self.tag_days.value()))

    def set_analytics_data(self, data: dict):
        payload = data or {}

        self.lbl_completed_today.setText(str(int(payload.get("completed_today") or 0)))
        self.lbl_completed_week.setText(str(int(payload.get("completed_this_week") or 0)))
        self.lbl_overdue.setText(str(int(payload.get("overdue_open") or 0)))
        self.lbl_no_due.setText(str(int(payload.get("open_no_due") or 0)))
        self.lbl_inbox.setText(str(int(payload.get("inbox_unprocessed") or 0)))
        self.lbl_active_archived.setText(
            f"{int(payload.get('active_open') or 0)} / {int(payload.get('archived_count') or 0)}"
        )
        self.lbl_projects.setText(
            f"{int(payload.get('project_stalled') or 0)} / "
            f"{int(payload.get('project_blocked') or 0)} / "
            f"{int(payload.get('project_no_next') or 0)}"
        )

        self.trend_list.clear()
        for row in payload.get("trend") or []:
            day = str(row.get("date") or "")
            count = int(row.get("count") or 0)
            self.trend_list.addItem(QListWidgetItem(f"{day}: {count} completed"))

        self.tags_list.clear()
        for row in payload.get("top_tags") or []:
            tag = str(row.get("tag") or "")
            count = int(row.get("count") or 0)
            self.tags_list.addItem(QListWidgetItem(f"{tag}: {count}"))

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
        if self.workload_list.count() == 0:
            self.workload_list.addItem(QListWidgetItem("No workload warnings."))

        self.hints_list.clear()
        for row in payload.get("scheduling_hints") or []:
            self.hints_list.addItem(QListWidgetItem(str(row.get("message") or "")))
        if self.hints_list.count() == 0:
            self.hints_list.addItem(QListWidgetItem("No scheduling hints."))
