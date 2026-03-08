from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QSize, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui_layout import (
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
)


class FilterPanel(QWidget):
    """
    Advanced filter controls (no search text here; search lives in the main bar).
    Emits changed() on any modification.
    """

    changed = Signal()

    def __init__(self, statuses: list[str], parent=None):
        super().__init__(parent)

        self._statuses = statuses

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        status_panel = SectionPanel(
            "Status",
            "Select which task statuses stay visible in the current view.",
        )
        v_status = QVBoxLayout()
        configure_box_layout(v_status)

        self.chk_all_status = QCheckBox("All")
        self.chk_all_status.setChecked(True)
        self.chk_all_status.setToolTip("Enable or disable all status filters at once.")
        self.chk_all_status.stateChanged.connect(self._on_all_status_changed)
        v_status.addWidget(self.chk_all_status)

        self.status_checks = []
        for s in statuses:
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.setToolTip(f"Include tasks with status: {s}.")
            cb.stateChanged.connect(self._emit_changed)
            self.status_checks.append(cb)
            v_status.addWidget(cb)

        status_panel.body_layout.addLayout(v_status)
        root.addWidget(status_panel)

        planning_panel = SectionPanel(
            "Priority and due range",
            "Keep the most relevant work visible without leaving the current "
            "perspective.",
        )
        h_prio = QFormLayout()
        configure_form_layout(h_prio, label_width=110)

        self.prio_min = QSpinBox()
        self.prio_min.setRange(1, 5)
        self.prio_min.setValue(1)
        self.prio_min.setToolTip("Minimum allowed priority for visible tasks.")
        self.prio_min.valueChanged.connect(self._emit_changed)

        self.prio_max = QSpinBox()
        self.prio_max.setRange(1, 5)
        self.prio_max.setValue(5)
        self.prio_max.setToolTip("Maximum allowed priority for visible tasks.")
        self.prio_max.valueChanged.connect(self._emit_changed)

        add_form_row(h_prio, "Minimum", self.prio_min)
        add_form_row(h_prio, "Maximum", self.prio_max)
        planning_panel.body_layout.addLayout(h_prio)

        v_due = QVBoxLayout()
        configure_box_layout(v_due)

        self.chk_due_range = QCheckBox("Enable due range")
        self.chk_due_range.setChecked(False)
        self.chk_due_range.setToolTip("Limit visible tasks to a due-date date range.")
        self.chk_due_range.stateChanged.connect(self._emit_changed)
        v_due.addWidget(self.chk_due_range)

        due_form = QFormLayout()
        configure_form_layout(due_form, label_width=80)
        self.due_from = QDateEdit()
        self.due_from.setCalendarPopup(True)
        self.due_from.setDisplayFormat("dd-MMM-yyyy")
        self.due_from.setDate(QDate.currentDate())
        self.due_from.setToolTip("Start date for due-date filter range.")
        self.due_from.dateChanged.connect(self._emit_changed)
        add_form_row(due_form, "From", self.due_from)

        self.due_to = QDateEdit()
        self.due_to.setCalendarPopup(True)
        self.due_to.setDisplayFormat("dd-MMM-yyyy")
        self.due_to.setDate(QDate.currentDate().addDays(30))
        self.due_to.setToolTip("End date for due-date filter range.")
        self.due_to.dateChanged.connect(self._emit_changed)
        add_form_row(due_form, "To", self.due_to)
        v_due.addLayout(due_form)
        planning_panel.body_layout.addLayout(v_due)
        root.addWidget(planning_panel)

        flags_panel = SectionPanel(
            "Options",
            "Apply visibility rules that affect done, overdue, blocked, and "
            "waiting work.",
        )
        v_flags = QVBoxLayout()
        configure_box_layout(v_flags)

        self.chk_hide_done = QCheckBox("Hide Done")
        self.chk_hide_done.setToolTip("Exclude tasks already marked Done.")
        self.chk_hide_done.stateChanged.connect(self._emit_changed)

        self.chk_overdue_only = QCheckBox("Overdue only")
        self.chk_overdue_only.setToolTip("Show only tasks with due date before today.")
        self.chk_overdue_only.stateChanged.connect(self._emit_changed)

        self.chk_blocked_only = QCheckBox("Blocked only")
        self.chk_blocked_only.setToolTip("Show only tasks blocked by dependencies.")
        self.chk_blocked_only.stateChanged.connect(self._emit_changed)

        self.chk_waiting_only = QCheckBox("Waiting only")
        self.chk_waiting_only.setToolTip("Show only tasks with waiting-for information.")
        self.chk_waiting_only.stateChanged.connect(self._emit_changed)

        self.chk_show_children = QCheckBox("Show children of matching parents")
        self.chk_show_children.setChecked(True)
        self.chk_show_children.setToolTip("Keep children visible when parent row matches search.")
        self.chk_show_children.stateChanged.connect(self._emit_changed)

        v_flags.addWidget(self.chk_hide_done)
        v_flags.addWidget(self.chk_overdue_only)
        v_flags.addWidget(self.chk_blocked_only)
        v_flags.addWidget(self.chk_waiting_only)
        v_flags.addWidget(self.chk_show_children)
        flags_panel.body_layout.addLayout(v_flags)
        root.addWidget(flags_panel)

        tags_panel = SectionPanel(
            "Tags",
            "Filter to tasks that contain all listed tags.",
        )
        tags_panel.header_actions.addWidget(self._make_reset_button())
        v_tags = QVBoxLayout()
        configure_box_layout(v_tags)
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("Comma-separated tags (all must match)")
        self.tags_input.setToolTip("Filter to tasks containing all listed tags.")
        self.tags_input.textChanged.connect(self._emit_changed)
        v_tags.addWidget(self.tags_input)
        tags_panel.body_layout.addLayout(v_tags)
        root.addWidget(tags_panel)

        root.addStretch(1)

    def sizeHint(self) -> QSize:
        return QSize(380, 560)

    def minimumSizeHint(self) -> QSize:
        return QSize(320, 420)

    def _make_reset_button(self) -> QPushButton:
        self.btn_reset = QPushButton("Reset filters")
        self.btn_reset.setToolTip("Reset all filter options to defaults.")
        self.btn_reset.clicked.connect(self.reset)
        return self.btn_reset

    def _emit_changed(self, *_):
        self.changed.emit()

    def _on_all_status_changed(self, state: int):
        checked = state == Qt.CheckState.Checked.value
        for cb in self.status_checks:
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self.changed.emit()

    # ---------- Read current filter state ----------
    def status_allowed(self) -> set[str] | None:
        # If all selected, return None (meaning no restriction)
        vals = {cb.text() for cb in self.status_checks if cb.isChecked()}
        if len(vals) == len(self.status_checks):
            return None
        return vals

    def priority_range(self) -> tuple[int | None, int | None]:
        # Always enabled; treated as restriction only if not full range
        pmin = int(self.prio_min.value())
        pmax = int(self.prio_max.value())
        if pmin == 1 and pmax == 5:
            return None, None
        return pmin, pmax

    def due_range(self) -> tuple[date | None, date | None]:
        if not self.chk_due_range.isChecked():
            return None, None
        d1 = self.due_from.date().toPython()
        d2 = self.due_to.date().toPython()
        return d1, d2

    def hide_done(self) -> bool:
        return self.chk_hide_done.isChecked()

    def overdue_only(self) -> bool:
        return self.chk_overdue_only.isChecked()

    def show_children_of_matches(self) -> bool:
        return self.chk_show_children.isChecked()

    def blocked_only(self) -> bool:
        return self.chk_blocked_only.isChecked()

    def waiting_only(self) -> bool:
        return self.chk_waiting_only.isChecked()

    def tag_filter(self) -> set[str]:
        raw = self.tags_input.text().strip()
        if not raw:
            return set()
        out = set()
        for part in raw.split(","):
            s = part.strip()
            if s:
                out.add(s)
        return out

    def snapshot(self) -> dict:
        dfrom, dto = self.due_range()
        return {
            "statuses": sorted(self.status_allowed() or []),
            "priority_min": self.priority_range()[0],
            "priority_max": self.priority_range()[1],
            "due_enabled": self.chk_due_range.isChecked(),
            "due_from": dfrom.isoformat() if dfrom else None,
            "due_to": dto.isoformat() if dto else None,
            "hide_done": self.hide_done(),
            "overdue_only": self.overdue_only(),
            "blocked_only": self.blocked_only(),
            "waiting_only": self.waiting_only(),
            "show_children_of_matches": self.show_children_of_matches(),
            "tags": sorted(self.tag_filter()),
        }

    def apply_snapshot(self, state: dict):
        data = state or {}
        statuses = set(data.get("statuses") or [])
        if statuses:
            self.chk_all_status.blockSignals(True)
            self.chk_all_status.setChecked(False)
            self.chk_all_status.blockSignals(False)
            for cb in self.status_checks:
                cb.blockSignals(True)
                cb.setChecked(cb.text() in statuses)
                cb.blockSignals(False)
        else:
            self.chk_all_status.setChecked(True)

        pmin = data.get("priority_min")
        pmax = data.get("priority_max")
        self.prio_min.setValue(int(pmin) if pmin is not None else 1)
        self.prio_max.setValue(int(pmax) if pmax is not None else 5)

        due_enabled = bool(data.get("due_enabled", False))
        self.chk_due_range.setChecked(due_enabled)
        due_from = data.get("due_from")
        due_to = data.get("due_to")
        if due_from:
            qd = QDate.fromString(str(due_from), "yyyy-MM-dd")
            if qd.isValid():
                self.due_from.setDate(qd)
        if due_to:
            qd = QDate.fromString(str(due_to), "yyyy-MM-dd")
            if qd.isValid():
                self.due_to.setDate(qd)

        self.chk_hide_done.setChecked(bool(data.get("hide_done", False)))
        self.chk_overdue_only.setChecked(bool(data.get("overdue_only", False)))
        self.chk_blocked_only.setChecked(bool(data.get("blocked_only", False)))
        self.chk_waiting_only.setChecked(bool(data.get("waiting_only", False)))
        self.chk_show_children.setChecked(bool(data.get("show_children_of_matches", True)))

        tags = data.get("tags") or []
        if isinstance(tags, list):
            self.tags_input.setText(", ".join(str(t) for t in tags if str(t).strip()))
        else:
            self.tags_input.setText("")

    # ---------- Reset ----------
    def reset(self):
        self.chk_all_status.setChecked(True)

        self.prio_min.setValue(1)
        self.prio_max.setValue(5)

        self.chk_due_range.setChecked(False)
        self.due_from.setDate(QDate.currentDate())
        self.due_to.setDate(QDate.currentDate().addDays(30))

        self.chk_hide_done.setChecked(False)
        self.chk_overdue_only.setChecked(False)
        self.chk_blocked_only.setChecked(False)
        self.chk_waiting_only.setChecked(False)
        self.chk_show_children.setChecked(True)
        self.tags_input.setText("")

        self.changed.emit()
