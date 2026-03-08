from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from delegates import DateEditorWithClear
from context_help import attach_context_help, create_context_help_header
from project_management import (
    DEFAULT_PHASE_NAMES,
    DELIVERABLE_STATUSES,
    MILESTONE_STATUSES,
    PROJECT_HEALTH_LABELS,
    PROJECT_HEALTH_STATES,
    REGISTER_ENTRY_TYPES,
    REGISTER_STATUSES,
    parse_iso_date,
)
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    SummaryCard,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_data_table,
    configure_form_layout,
)


class DependencyPickerDialog(QDialog):
    def __init__(self, targets: list[dict], selected_refs: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select dependencies")
        self.resize(420, 420)

        selected = {
            (str(row.get("kind") or ""), int(row.get("id") or 0))
            for row in (selected_refs or [])
            if row.get("id") is not None
        }

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        self.help_header = create_context_help_header(
            "Select dependencies",
            "dependency_picker_dialog",
            self,
            tooltip="Open help for project dependencies",
        )
        root.addWidget(self.help_header)

        self.list = QListWidget()
        self.list.setToolTip(
            "Choose predecessor items. The selected milestone stays blocked "
            "until these items complete."
        )
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self.list, 1)

        for row in targets:
            kind = str(row.get("kind") or "")
            item_id = int(row.get("id") or 0)
            label = str(row.get("label") or f"{kind} {item_id}")
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, {"kind": kind, "id": item_id})
            item.setCheckState(
                Qt.CheckState.Checked if (kind, item_id) in selected else Qt.CheckState.Unchecked
            )
            self.list.addItem(item)

        actions = QHBoxLayout()
        self.ok_btn = QPushButton("Accept")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(actions, self.ok_btn, self.cancel_btn)
        root.addLayout(actions)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def selected_refs(self) -> list[dict]:
        refs: list[dict] = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            payload = item.data(Qt.ItemDataRole.UserRole) or {}
            refs.append(
                {
                    "kind": str(payload.get("kind") or ""),
                    "id": int(payload.get("id") or 0),
                }
            )
        return refs


class MilestoneDialog(QDialog):
    def __init__(self, phases: list[dict], task_options: list[dict], milestone_options: list[dict], payload: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Milestone")
        self.resize(540, 560)
        self._dependency_targets = [
            {
                "kind": "task",
                "id": int(row.get("id") or 0),
                "label": f"Task: {str(row.get('description') or row.get('label') or '')}",
            }
            for row in task_options
        ] + [
            {
                "kind": "milestone",
                "id": int(row.get("id") or 0),
                "label": f"Milestone: {str(row.get('title') or row.get('label') or '')}",
            }
            for row in milestone_options
        ]
        self._selected_dependencies: list[dict] = list((payload or {}).get("dependencies") or [])

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        self.help_header = create_context_help_header(
            "Milestone",
            "milestone_dialog",
            self,
            tooltip="Open help for milestones",
        )
        root.addWidget(self.help_header)

        form = QFormLayout()
        configure_form_layout(form, label_width=150)

        self.title_edit = QPlainTextEdit()
        self.title_edit.setFixedHeight(48)
        add_form_row(form, "Title", self.title_edit)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(90)
        add_form_row(form, "Description", self.description_edit)

        self.phase_combo = QComboBox()
        self.phase_combo.addItem("(none)", None)
        for row in phases:
            self.phase_combo.addItem(str(row.get("name") or ""), int(row.get("id")))
        add_form_row(form, "Phase", self.phase_combo)

        self.linked_task_combo = QComboBox()
        self.linked_task_combo.addItem("(none)", None)
        for row in task_options:
            self.linked_task_combo.addItem(str(row.get("description") or row.get("label") or ""), int(row.get("id")))
        add_form_row(form, "Linked task", self.linked_task_combo)

        self.start_date = DateEditorWithClear()
        add_form_row(form, "Start date", self.start_date)

        self.target_date = DateEditorWithClear()
        add_form_row(form, "Target date", self.target_date)

        self.baseline_date = DateEditorWithClear()
        add_form_row(form, "Baseline target", self.baseline_date)

        self.status_combo = QComboBox()
        for status in MILESTONE_STATUSES:
            self.status_combo.addItem(status.replace("_", " ").title(), status)
        add_form_row(form, "Status", self.status_combo)

        self.progress_spin = QSpinBox()
        self.progress_spin.setRange(0, 100)
        self.progress_spin.setSuffix(" %")
        add_form_row(form, "Progress", self.progress_spin)

        dep_row = QHBoxLayout()
        configure_box_layout(dep_row)
        self.dep_summary = QLabel("No dependencies")
        self.dep_btn = QPushButton("Choose…")
        dep_row.addWidget(self.dep_summary, 1)
        dep_row.addWidget(self.dep_btn)
        add_form_row(form, "Blocked by", self._wrap(dep_row))

        root.addLayout(form)

        actions = QHBoxLayout()
        self.ok_btn = QPushButton("Accept")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(actions, self.ok_btn, self.cancel_btn)
        root.addLayout(actions)

        self.dep_btn.clicked.connect(self._choose_dependencies)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        self.status_combo.currentIndexChanged.connect(self._sync_completion_defaults)

        if payload:
            self._apply_payload(payload)
        self._refresh_dependency_summary()

    def _wrap(self, layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _sync_completion_defaults(self):
        if str(self.status_combo.currentData() or "") == "completed":
            self.progress_spin.setValue(100)

    def _choose_dependencies(self):
        dlg = DependencyPickerDialog(self._dependency_targets, self._selected_dependencies, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._selected_dependencies = dlg.selected_refs()
        self._refresh_dependency_summary()

    def _refresh_dependency_summary(self):
        count = len(self._selected_dependencies)
        self.dep_summary.setText("No dependencies" if count == 0 else f"{count} selected")

    def _apply_payload(self, payload: dict):
        self.title_edit.setPlainText(str(payload.get("title") or ""))
        self.description_edit.setPlainText(str(payload.get("description") or ""))
        phase_idx = self.phase_combo.findData(payload.get("phase_id"))
        self.phase_combo.setCurrentIndex(phase_idx if phase_idx >= 0 else 0)
        task_idx = self.linked_task_combo.findData(payload.get("linked_task_id"))
        self.linked_task_combo.setCurrentIndex(task_idx if task_idx >= 0 else 0)
        self.start_date.set_iso_date(payload.get("start_date"))
        self.target_date.set_iso_date(payload.get("target_date"))
        self.baseline_date.set_iso_date(payload.get("baseline_target_date"))
        status_idx = self.status_combo.findData(str(payload.get("status") or "planned"))
        self.status_combo.setCurrentIndex(status_idx if status_idx >= 0 else 0)
        self.progress_spin.setValue(max(0, min(100, int(payload.get("progress_percent") or 0))))

    def payload(self) -> dict:
        status = str(self.status_combo.currentData() or "planned")
        progress = int(self.progress_spin.value())
        completed_at = date.today().isoformat() if status == "completed" else None
        return {
            "title": self.title_edit.toPlainText().strip(),
            "description": self.description_edit.toPlainText(),
            "phase_id": self.phase_combo.currentData(),
            "linked_task_id": self.linked_task_combo.currentData(),
            "start_date": self.start_date.iso_date(),
            "target_date": self.target_date.iso_date(),
            "baseline_target_date": self.baseline_date.iso_date(),
            "status": status,
            "progress_percent": progress,
            "completed_at": completed_at,
            "dependencies": list(self._selected_dependencies),
        }


class DeliverableDialog(QDialog):
    def __init__(self, phases: list[dict], task_options: list[dict], milestone_options: list[dict], payload: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Deliverable")
        self.resize(540, 560)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        self.help_header = create_context_help_header(
            "Deliverable",
            "deliverable_dialog",
            self,
            tooltip="Open help for deliverables",
        )
        root.addWidget(self.help_header)

        form = QFormLayout()
        configure_form_layout(form, label_width=150)

        self.title_edit = QPlainTextEdit()
        self.title_edit.setFixedHeight(48)
        add_form_row(form, "Title", self.title_edit)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(90)
        add_form_row(form, "Description", self.description_edit)

        self.phase_combo = QComboBox()
        self.phase_combo.addItem("(none)", None)
        for row in phases:
            self.phase_combo.addItem(str(row.get("name") or ""), int(row.get("id")))
        add_form_row(form, "Phase", self.phase_combo)

        self.linked_task_combo = QComboBox()
        self.linked_task_combo.addItem("(none)", None)
        for row in task_options:
            self.linked_task_combo.addItem(str(row.get("description") or row.get("label") or ""), int(row.get("id")))
        add_form_row(form, "Linked task", self.linked_task_combo)

        self.linked_milestone_combo = QComboBox()
        self.linked_milestone_combo.addItem("(none)", None)
        for row in milestone_options:
            self.linked_milestone_combo.addItem(str(row.get("title") or row.get("label") or ""), int(row.get("id")))
        add_form_row(form, "Linked milestone", self.linked_milestone_combo)

        self.due_date = DateEditorWithClear()
        add_form_row(form, "Due date", self.due_date)

        self.baseline_due_date = DateEditorWithClear()
        add_form_row(form, "Baseline due", self.baseline_due_date)

        self.status_combo = QComboBox()
        for status in DELIVERABLE_STATUSES:
            self.status_combo.addItem(status.replace("_", " ").title(), status)
        add_form_row(form, "Status", self.status_combo)

        self.version_ref = QPlainTextEdit()
        self.version_ref.setFixedHeight(48)
        add_form_row(form, "Version/ref", self.version_ref)

        self.acceptance = QPlainTextEdit()
        self.acceptance.setFixedHeight(90)
        add_form_row(form, "Acceptance criteria", self.acceptance)

        root.addLayout(form)

        actions = QHBoxLayout()
        self.ok_btn = QPushButton("Accept")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(actions, self.ok_btn, self.cancel_btn)
        root.addLayout(actions)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        if payload:
            self._apply_payload(payload)

    def _apply_payload(self, payload: dict):
        self.title_edit.setPlainText(str(payload.get("title") or ""))
        self.description_edit.setPlainText(str(payload.get("description") or ""))
        phase_idx = self.phase_combo.findData(payload.get("phase_id"))
        self.phase_combo.setCurrentIndex(phase_idx if phase_idx >= 0 else 0)
        task_idx = self.linked_task_combo.findData(payload.get("linked_task_id"))
        self.linked_task_combo.setCurrentIndex(task_idx if task_idx >= 0 else 0)
        milestone_idx = self.linked_milestone_combo.findData(payload.get("linked_milestone_id"))
        self.linked_milestone_combo.setCurrentIndex(milestone_idx if milestone_idx >= 0 else 0)
        self.due_date.set_iso_date(payload.get("due_date"))
        self.baseline_due_date.set_iso_date(payload.get("baseline_due_date"))
        status_idx = self.status_combo.findData(str(payload.get("status") or "planned"))
        self.status_combo.setCurrentIndex(status_idx if status_idx >= 0 else 0)
        self.version_ref.setPlainText(str(payload.get("version_ref") or ""))
        self.acceptance.setPlainText(str(payload.get("acceptance_criteria") or ""))

    def payload(self) -> dict:
        status = str(self.status_combo.currentData() or "planned")
        completed_at = date.today().isoformat() if status == "completed" else None
        return {
            "title": self.title_edit.toPlainText().strip(),
            "description": self.description_edit.toPlainText(),
            "phase_id": self.phase_combo.currentData(),
            "linked_task_id": self.linked_task_combo.currentData(),
            "linked_milestone_id": self.linked_milestone_combo.currentData(),
            "due_date": self.due_date.iso_date(),
            "baseline_due_date": self.baseline_due_date.iso_date(),
            "acceptance_criteria": self.acceptance.toPlainText(),
            "version_ref": self.version_ref.toPlainText(),
            "status": status,
            "completed_at": completed_at,
        }


class RegisterEntryDialog(QDialog):
    def __init__(self, task_options: list[dict], milestone_options: list[dict], payload: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Register entry")
        self.resize(540, 560)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        self.help_header = create_context_help_header(
            "Register entry",
            "register_entry_dialog",
            self,
            tooltip="Open help for project registers",
        )
        root.addWidget(self.help_header)

        form = QFormLayout()
        configure_form_layout(form, label_width=150)

        self.type_combo = QComboBox()
        for value in REGISTER_ENTRY_TYPES:
            self.type_combo.addItem(value.title(), value)
        add_form_row(form, "Type", self.type_combo)

        self.title_edit = QPlainTextEdit()
        self.title_edit.setFixedHeight(48)
        add_form_row(form, "Title", self.title_edit)

        self.details_edit = QPlainTextEdit()
        self.details_edit.setFixedHeight(110)
        add_form_row(form, "Details", self.details_edit)

        self.status_combo = QComboBox()
        for value in REGISTER_STATUSES:
            self.status_combo.addItem(value.title(), value)
        add_form_row(form, "Status", self.status_combo)

        self.severity_spin = QSpinBox()
        self.severity_spin.setRange(0, 5)
        self.severity_spin.setSpecialValueText("None")
        add_form_row(form, "Severity", self.severity_spin)

        self.review_date = DateEditorWithClear()
        add_form_row(form, "Review date", self.review_date)

        self.linked_task_combo = QComboBox()
        self.linked_task_combo.addItem("(none)", None)
        for row in task_options:
            self.linked_task_combo.addItem(str(row.get("description") or row.get("label") or ""), int(row.get("id")))
        add_form_row(form, "Linked task", self.linked_task_combo)

        self.linked_milestone_combo = QComboBox()
        self.linked_milestone_combo.addItem("(none)", None)
        for row in milestone_options:
            self.linked_milestone_combo.addItem(str(row.get("title") or row.get("label") or ""), int(row.get("id")))
        add_form_row(form, "Linked milestone", self.linked_milestone_combo)

        root.addLayout(form)

        actions = QHBoxLayout()
        self.ok_btn = QPushButton("Accept")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(actions, self.ok_btn, self.cancel_btn)
        root.addLayout(actions)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        if payload:
            self._apply_payload(payload)

    def _apply_payload(self, payload: dict):
        type_idx = self.type_combo.findData(str(payload.get("entry_type") or "risk"))
        self.type_combo.setCurrentIndex(type_idx if type_idx >= 0 else 0)
        self.title_edit.setPlainText(str(payload.get("title") or ""))
        self.details_edit.setPlainText(str(payload.get("details") or ""))
        status_idx = self.status_combo.findData(str(payload.get("status") or "open"))
        self.status_combo.setCurrentIndex(status_idx if status_idx >= 0 else 0)
        severity = int(payload.get("severity") or 0)
        self.severity_spin.setValue(max(0, min(5, severity)))
        self.review_date.set_iso_date(payload.get("review_date"))
        task_idx = self.linked_task_combo.findData(payload.get("linked_task_id"))
        self.linked_task_combo.setCurrentIndex(task_idx if task_idx >= 0 else 0)
        milestone_idx = self.linked_milestone_combo.findData(payload.get("linked_milestone_id"))
        self.linked_milestone_combo.setCurrentIndex(milestone_idx if milestone_idx >= 0 else 0)

    def payload(self) -> dict:
        severity = int(self.severity_spin.value())
        return {
            "entry_type": self.type_combo.currentData(),
            "title": self.title_edit.toPlainText().strip(),
            "details": self.details_edit.toPlainText(),
            "status": self.status_combo.currentData(),
            "severity": None if severity <= 0 else severity,
            "review_date": self.review_date.iso_date(),
            "linked_task_id": self.linked_task_combo.currentData(),
            "linked_milestone_id": self.linked_milestone_combo.currentData(),
        }


class ProjectTimelineWidget(QWidget):
    rowActivated = Signal(str, int)
    rescheduleRequested = Signal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._row_bounds: list[tuple[QRectF, str, int]] = []
        self._bar_bounds: list[dict] = []
        self._min_date: date | None = None
        self._span_days = 1
        self._timeline_left = 0.0
        self._timeline_width = 1.0
        self._drag_candidate: dict | None = None
        self._dragging: dict | None = None
        self._drag_preview_delta_days = 0
        self.setMinimumHeight(220)
        self.setMinimumWidth(760)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict]):
        self._rows = list(rows or [])
        height = max(220, 48 + (len(self._rows) * 28))
        self.setMinimumHeight(height)
        self._clear_drag_state()
        self.update()

    def mouseDoubleClickEvent(self, event):
        pos = event.position()
        for rect, kind, item_id in self._row_bounds:
            if rect.contains(pos):
                self.rowActivated.emit(kind, int(item_id))
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._bar_hit(event.position())
            if hit is not None:
                self._drag_candidate = {
                    "kind": str(hit["kind"]),
                    "item_id": int(hit["item_id"]),
                    "press_pos": QPointF(event.position()),
                }
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_candidate is None:
            super().mouseMoveEvent(event)
            return
        dx = float(event.position().x() - self._drag_candidate["press_pos"].x())
        if self._dragging is None and abs(dx) >= QApplication.startDragDistance():
            self._dragging = dict(self._drag_candidate)
        if self._dragging is not None:
            delta_days = self._delta_days_from_pixels(dx)
            if delta_days != self._drag_preview_delta_days:
                self._drag_preview_delta_days = delta_days
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_candidate is not None:
            kind = str(self._drag_candidate["kind"])
            item_id = int(self._drag_candidate["item_id"])
            delta_days = int(self._drag_preview_delta_days)
            was_dragging = self._dragging is not None
            self._clear_drag_state()
            if was_dragging and delta_days != 0:
                self.rescheduleRequested.emit(kind, item_id, delta_days)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _clear_drag_state(self):
        self._drag_candidate = None
        self._dragging = None
        self._drag_preview_delta_days = 0

    def _bar_hit(self, pos: QPointF) -> dict | None:
        for info in reversed(self._bar_bounds):
            if info["rect"].adjusted(-4, -4, 4, 4).contains(pos):
                return info
        return None

    def _delta_days_from_pixels(self, delta_x: float) -> int:
        width = max(1.0, float(self._timeline_width or 1.0))
        span_days = max(1, int(self._span_days or 1))
        return int(round((float(delta_x) / width) * span_days))

    @staticmethod
    def _shift_date(value: date | None, delta_days: int) -> date | None:
        if value is None:
            return None
        return value + timedelta(days=int(delta_days))

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self.palette().base())

        self._row_bounds = []
        self._bar_bounds = []
        rows = list(self._rows or [])
        if not rows:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No timeline data available for this project.")
            return

        all_dates = []
        for row in rows:
            for key in ("start_date", "end_date", "baseline_date"):
                parsed = parse_iso_date(row.get(key))
                if parsed is not None:
                    all_dates.append(parsed)
        if not all_dates:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Timeline needs dated tasks, milestones, or deliverables.")
            return

        min_date = min(all_dates)
        max_date = max(all_dates)
        if min_date == max_date:
            max_date = min_date + timedelta(days=1)
        span_days = max(1, (max_date - min_date).days)
        self._min_date = min_date
        self._span_days = span_days

        label_width = 220
        header_height = 30
        row_height = 26
        left = 12
        top = 12
        timeline_left = left + label_width
        timeline_width = max(220, self.width() - timeline_left - 12)
        self._timeline_left = float(timeline_left)
        self._timeline_width = float(timeline_width)

        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(left, top, label_width, header_height), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Item")
        painter.drawText(
            QRectF(timeline_left, top, timeline_width, header_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{min_date.isoformat()}  ->  {max_date.isoformat()}",
        )

        grid_pen = QPen(self.palette().mid().color())
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        for offset in range(0, span_days + 1, max(1, span_days // 8 or 1)):
            x = timeline_left + ((offset / span_days) * timeline_width)
            painter.drawLine(int(x), top + header_height, int(x), self.height() - 12)

        for index, row in enumerate(rows):
            y = top + header_height + (index * row_height)
            row_rect = QRectF(left, y, self.width() - 24, row_height)
            if index % 2 == 0:
                painter.fillRect(row_rect, self.palette().alternateBase())
            label = str(row.get("label") or "")
            phase = str(row.get("phase_name") or "")
            painter.setPen(self.palette().text().color())
            painter.drawText(
                QRectF(left + 4, y, label_width - 8, row_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{label} [{phase}]" if phase else label,
            )

            start_date = parse_iso_date(row.get("start_date")) or parse_iso_date(row.get("end_date"))
            end_date = parse_iso_date(row.get("end_date")) or start_date
            baseline = parse_iso_date(row.get("baseline_date"))
            if start_date is None or end_date is None:
                continue

            delta_days = 0
            if (
                self._dragging is not None
                and str(self._dragging.get("kind") or "") == str(row.get("kind") or "")
                and int(self._dragging.get("item_id") or 0) == int(row.get("item_id") or 0)
            ):
                delta_days = int(self._drag_preview_delta_days)
            draw_start_date = self._shift_date(start_date, delta_days) or start_date
            draw_end_date = self._shift_date(end_date, delta_days) or end_date

            start_x = timeline_left + (((draw_start_date - min_date).days / span_days) * timeline_width)
            end_x = timeline_left + (((draw_end_date - min_date).days / span_days) * timeline_width)
            if end_x <= start_x:
                end_x = start_x + 6
            bar_rect = QRectF(start_x, y + 6, max(6, end_x - start_x), row_height - 12)

            status = str(row.get("status") or "").lower()
            blocked = bool(row.get("blocked"))
            color = QColor("#3b82f6")
            if blocked:
                color = QColor("#ef4444")
            elif status in {"completed", "done", "on_track"}:
                color = QColor("#16a34a")
            elif status in {"blocked", "delayed", "at_risk", "awaiting_external_input", "scope_drifting"}:
                color = QColor("#f97316")
            painter.fillRect(bar_rect, color)
            if delta_days != 0:
                painter.setPen(QPen(self.palette().highlight().color(), 2))
                painter.drawRect(bar_rect)

            if baseline is not None:
                baseline_x = timeline_left + (((baseline - min_date).days / span_days) * timeline_width)
                painter.setPen(QPen(QColor("#111827"), 2))
                painter.drawLine(int(baseline_x), int(y + 3), int(baseline_x), int(y + row_height - 3))

            self._row_bounds.append((row_rect, str(row.get("kind") or ""), int(row.get("item_id") or 0)))
            if str(row.get("kind") or "") in {"task", "milestone", "deliverable"}:
                self._bar_bounds.append(
                    {
                        "rect": QRectF(bar_rect),
                        "kind": str(row.get("kind") or ""),
                        "item_id": int(row.get("item_id") or 0),
                    }
                )


class ProjectCockpitPanel(QWidget):
    projectSelected = Signal(int)
    saveProfileRequested = Signal(int, dict)
    saveBaselineRequested = Signal(int, object, object)
    addPhaseRequested = Signal(int, str)
    renamePhaseRequested = Signal(int, str)
    deletePhaseRequested = Signal(int)
    addMilestoneRequested = Signal(dict)
    editMilestoneRequested = Signal(int, dict)
    deleteMilestoneRequested = Signal(int)
    addDeliverableRequested = Signal(dict)
    editDeliverableRequested = Signal(int, dict)
    deleteDeliverableRequested = Signal(int)
    addRegisterEntryRequested = Signal(dict)
    editRegisterEntryRequested = Signal(int, dict)
    deleteRegisterEntryRequested = Signal(int)
    focusTaskRequested = Signal(int)
    timelineRescheduleRequested = Signal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_project_id: int | None = None
        self._dashboard: dict | None = None
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        nav_panel = SectionPanel(
            "Project cockpit",
            "Select a project, review delivery health, and manage milestones, "
            "deliverables, risks, timeline, and workload from one place.",
        )
        self.help_btn = attach_context_help(
            nav_panel,
            "project_cockpit",
            self,
            tooltip="Open help for the project cockpit",
        )
        nav_layout = QFormLayout()
        configure_form_layout(nav_layout, label_width=90)
        self.project_combo = QComboBox()
        self.project_combo.setToolTip("Jump directly to a project context.")
        nav_layout.addRow("Project", self.project_combo)
        nav_panel.body_layout.addLayout(nav_layout)
        root.addWidget(nav_panel)

        summary_panel = SectionPanel(
            "Project summary",
            "Core signals stay visible above the tabs so the cockpit has an "
            "obvious starting point.",
        )
        self.header_label = QLabel("No project selected")
        self.header_label.setWordWrap(True)
        summary_panel.body_layout.addWidget(self.header_label)

        summary_grid = QGridLayout()
        configure_box_layout(summary_grid, spacing=8)
        self.summary_health_card = SummaryCard("Health")
        self.summary_milestone_card = SummaryCard("Next milestone")
        self.summary_blockers_card = SummaryCard("Blockers")
        self.summary_deliverables_card = SummaryCard("Deliverables due")
        summary_grid.addWidget(self.summary_health_card, 0, 0)
        summary_grid.addWidget(self.summary_milestone_card, 0, 1)
        summary_grid.addWidget(self.summary_blockers_card, 1, 0)
        summary_grid.addWidget(self.summary_deliverables_card, 1, 1)
        summary_panel.body_layout.addLayout(summary_grid)
        root.addWidget(summary_panel)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self._build_overview_tab()
        self._build_milestones_tab()
        self._build_deliverables_tab()
        self._build_register_tab()
        self._build_timeline_tab()
        self._build_capacity_tab()

        self.project_combo.currentIndexChanged.connect(self._emit_project_change)

    def _build_overview_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        configure_box_layout(layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        definition_panel = SectionPanel(
            "Project definition",
            "Define objective, scope, ownership, timing, health override, "
            "and the summary context for the selected project.",
        )
        self.save_profile_btn = QPushButton("Save project definition")
        self.save_profile_btn.setToolTip("Save the project definition fields shown in this section.")
        definition_panel.header_actions.addWidget(self.save_profile_btn)
        definition_form = QFormLayout()
        configure_form_layout(definition_form, label_width=140)
        definition_panel.body_layout.addLayout(definition_form)

        self.objective_edit = QPlainTextEdit()
        self.objective_edit.setFixedHeight(52)
        add_form_row(definition_form, "Objective", self.objective_edit)
        self.scope_edit = QPlainTextEdit()
        self.scope_edit.setFixedHeight(60)
        add_form_row(definition_form, "Scope", self.scope_edit)
        self.out_of_scope_edit = QPlainTextEdit()
        self.out_of_scope_edit.setFixedHeight(60)
        add_form_row(definition_form, "Out of scope", self.out_of_scope_edit)
        self.owner_edit = QPlainTextEdit()
        self.owner_edit.setFixedHeight(42)
        add_form_row(definition_form, "Owner", self.owner_edit)
        self.stakeholders_edit = QPlainTextEdit()
        self.stakeholders_edit.setFixedHeight(52)
        add_form_row(definition_form, "Stakeholders", self.stakeholders_edit)
        self.target_date_edit = DateEditorWithClear()
        add_form_row(definition_form, "Target date", self.target_date_edit)
        self.success_criteria_edit = QPlainTextEdit()
        self.success_criteria_edit.setFixedHeight(60)
        add_form_row(definition_form, "Success criteria", self.success_criteria_edit)
        self.health_override_combo = QComboBox()
        self.health_override_combo.addItem("(automatic)", None)
        for state in PROJECT_HEALTH_STATES:
            self.health_override_combo.addItem(
                PROJECT_HEALTH_LABELS.get(state, state.title()),
                state,
            )
        add_form_row(definition_form, "Manual health", self.health_override_combo)
        self.summary_edit = QPlainTextEdit()
        self.summary_edit.setFixedHeight(90)
        add_form_row(definition_form, "Summary / background", self.summary_edit)
        self.category_edit = QPlainTextEdit()
        self.category_edit.setFixedHeight(42)
        add_form_row(definition_form, "Category", self.category_edit)
        splitter.addWidget(definition_panel)

        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        configure_box_layout(right_layout)

        status_panel = SectionPanel(
            "Status details",
            "Detailed health, milestone, blocker, effort, and baseline signals "
            "for the current project.",
        )
        summary_layout = QFormLayout()
        configure_form_layout(summary_layout, label_width=190)
        self.lbl_health = QLabel("-")
        self.lbl_next_milestone = QLabel("-")
        self.lbl_blockers = QLabel("-")
        self.lbl_due_soon = QLabel("-")
        self.lbl_effort = QLabel("-")
        self.lbl_variance = QLabel("-")
        for label in (
            self.lbl_health,
            self.lbl_next_milestone,
            self.lbl_blockers,
            self.lbl_due_soon,
            self.lbl_effort,
            self.lbl_variance,
        ):
            label.setWordWrap(True)
        add_form_row(summary_layout, "Health", self.lbl_health)
        add_form_row(summary_layout, "Next milestone", self.lbl_next_milestone)
        add_form_row(summary_layout, "Blockers / waiting", self.lbl_blockers)
        add_form_row(summary_layout, "Due soon", self.lbl_due_soon)
        add_form_row(summary_layout, "Effort", self.lbl_effort)
        add_form_row(summary_layout, "Baseline variance", self.lbl_variance)
        status_panel.body_layout.addLayout(summary_layout)
        right_layout.addWidget(status_panel)

        baseline_panel = SectionPanel(
            "Baselines",
            "Track original target and effort commitments for variance analysis.",
        )
        self.save_baseline_btn = QPushButton("Save baseline")
        self.save_baseline_btn.setToolTip("Save baseline target date and effort values.")
        baseline_panel.header_actions.addWidget(self.save_baseline_btn)
        baseline_form = QFormLayout()
        configure_form_layout(baseline_form, label_width=150)
        self.baseline_target_date = DateEditorWithClear()
        add_form_row(baseline_form, "Baseline target", self.baseline_target_date)
        self.baseline_effort_spin = QSpinBox()
        self.baseline_effort_spin.setRange(-1, 1_000_000)
        self.baseline_effort_spin.setSpecialValueText("None")
        self.baseline_effort_spin.setSuffix(" min")
        add_form_row(baseline_form, "Baseline effort", self.baseline_effort_spin)
        baseline_panel.body_layout.addLayout(baseline_form)
        right_layout.addWidget(baseline_panel)

        phases_panel = SectionPanel(
            "Phases",
            "Group tasks, milestones, and deliverables into project-specific "
            "phases without leaving the cockpit.",
        )
        phases_actions = QHBoxLayout()
        configure_box_layout(phases_actions)
        self.add_phase_btn = QPushButton("Add phase")
        self.rename_phase_btn = QPushButton("Rename")
        self.delete_phase_btn = QPushButton("Remove")
        add_left_aligned_buttons(
            phases_actions,
            self.add_phase_btn,
            self.rename_phase_btn,
            self.delete_phase_btn,
        )
        phases_panel.body_layout.addLayout(phases_actions)
        self.phases_list = QListWidget()
        self.phases_list.setToolTip("Project phases used for grouping tasks, milestones, and deliverables.")
        self.phases_list.setAlternatingRowColors(True)
        self.phases_stack = EmptyStateStack(
            self.phases_list,
            "No phases yet.",
            "Add a phase to group related work across tasks, milestones, "
            "and deliverables.",
        )
        phases_panel.body_layout.addWidget(self.phases_stack, 1)
        right_layout.addWidget(phases_panel, 1)
        splitter.addWidget(right_column)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.save_profile_btn.clicked.connect(self._emit_save_profile)
        self.save_baseline_btn.clicked.connect(self._emit_save_baseline)
        self.add_phase_btn.clicked.connect(self._prompt_add_phase)
        self.rename_phase_btn.clicked.connect(self._prompt_rename_phase)
        self.delete_phase_btn.clicked.connect(self._prompt_delete_phase)

        self.tabs.addTab(page, "Overview")

    def _build_milestones_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        configure_box_layout(layout)
        section = SectionPanel(
            "Milestones",
            "Track project checkpoints, target dates, phase placement, and "
            "blocking dependencies in one dense list.",
        )
        layout.addWidget(section, 1)

        toolbar = QHBoxLayout()
        configure_box_layout(toolbar)
        self.milestones_meta = QLabel("0 milestones")
        self.milestones_meta.setWordWrap(True)
        toolbar.addWidget(self.milestones_meta, 1)

        self.add_milestone_btn = QPushButton("Add")
        self.edit_milestone_btn = QPushButton("Edit")
        self.complete_milestone_btn = QPushButton("Toggle complete")
        self.delete_milestone_btn = QPushButton("Delete")
        add_left_aligned_buttons(
            toolbar,
            self.add_milestone_btn,
            self.edit_milestone_btn,
            self.complete_milestone_btn,
            self.delete_milestone_btn,
            trailing_stretch=False,
        )
        section.body_layout.addLayout(toolbar)

        self.milestones_table = self._make_table(
            ["Title", "Phase", "Start", "Target", "Baseline", "Status", "Progress", "Blocked"]
        )
        self.milestones_table.itemDoubleClicked.connect(lambda _item: self._edit_selected_milestone())
        self.milestones_stack = EmptyStateStack(
            self.milestones_table,
            "No milestones yet.",
            "Add one to track a concrete project checkpoint or phase gate.",
        )
        section.body_layout.addWidget(self.milestones_stack, 1)
        self.add_milestone_btn.clicked.connect(self._add_milestone)
        self.edit_milestone_btn.clicked.connect(self._edit_selected_milestone)
        self.complete_milestone_btn.clicked.connect(self._toggle_complete_milestone)
        self.delete_milestone_btn.clicked.connect(self._delete_selected_milestone)
        self.tabs.addTab(page, "Milestones")

    def _build_deliverables_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        configure_box_layout(layout)
        section = SectionPanel(
            "Deliverables",
            "Manage concrete outputs, due dates, baseline commitments, linked "
            "milestones, and acceptance criteria.",
        )
        layout.addWidget(section, 1)

        toolbar = QHBoxLayout()
        configure_box_layout(toolbar)
        self.deliverables_meta = QLabel("0 deliverables")
        self.deliverables_meta.setWordWrap(True)
        toolbar.addWidget(self.deliverables_meta, 1)

        self.add_deliverable_btn = QPushButton("Add")
        self.edit_deliverable_btn = QPushButton("Edit")
        self.complete_deliverable_btn = QPushButton("Toggle complete")
        self.delete_deliverable_btn = QPushButton("Delete")
        add_left_aligned_buttons(
            toolbar,
            self.add_deliverable_btn,
            self.edit_deliverable_btn,
            self.complete_deliverable_btn,
            self.delete_deliverable_btn,
            trailing_stretch=False,
        )
        section.body_layout.addLayout(toolbar)

        self.deliverables_table = self._make_table(
            ["Title", "Phase", "Due", "Baseline", "Status", "Version", "Linked"]
        )
        self.deliverables_table.itemDoubleClicked.connect(lambda _item: self._edit_selected_deliverable())
        self.deliverables_stack = EmptyStateStack(
            self.deliverables_table,
            "No deliverables yet.",
            "Add a deliverable to track a concrete project output and its "
            "acceptance criteria.",
        )
        section.body_layout.addWidget(self.deliverables_stack, 1)
        self.add_deliverable_btn.clicked.connect(self._add_deliverable)
        self.edit_deliverable_btn.clicked.connect(self._edit_selected_deliverable)
        self.complete_deliverable_btn.clicked.connect(self._toggle_complete_deliverable)
        self.delete_deliverable_btn.clicked.connect(self._delete_selected_deliverable)
        self.tabs.addTab(page, "Deliverables")

    def _build_register_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        configure_box_layout(layout)
        section = SectionPanel(
            "Risks, issues, assumptions, and decisions",
            "Keep the structured project register close to the delivery "
            "surface instead of burying it in notes.",
        )
        layout.addWidget(section, 1)

        filter_row = QHBoxLayout()
        configure_box_layout(filter_row)
        filter_row.addWidget(QLabel("Type filter"))
        self.register_filter = QComboBox()
        self.register_filter.addItem("All", None)
        for value in REGISTER_ENTRY_TYPES:
            self.register_filter.addItem(value.title(), value)
        filter_row.addWidget(self.register_filter)

        self.register_meta = QLabel("0 register entries")
        self.register_meta.setWordWrap(True)
        filter_row.addWidget(self.register_meta, 1)

        self.add_register_btn = QPushButton("Add")
        self.edit_register_btn = QPushButton("Edit")
        self.resolve_register_btn = QPushButton("Toggle resolved")
        self.delete_register_btn = QPushButton("Delete")
        add_left_aligned_buttons(
            filter_row,
            self.add_register_btn,
            self.edit_register_btn,
            self.resolve_register_btn,
            self.delete_register_btn,
            trailing_stretch=False,
        )
        section.body_layout.addLayout(filter_row)

        self.register_table = self._make_table(["Type", "Title", "Status", "Severity", "Review", "Links"])
        self.register_table.itemDoubleClicked.connect(lambda _item: self._edit_selected_register_entry())
        self.register_stack = EmptyStateStack(
            self.register_table,
            "No register entries yet.",
            "Add a risk, issue, assumption, or decision to make project "
            "governance visible and actionable.",
        )
        section.body_layout.addWidget(self.register_stack, 1)
        self.register_filter.currentIndexChanged.connect(self._refresh_register_table_only)
        self.add_register_btn.clicked.connect(self._add_register_entry)
        self.edit_register_btn.clicked.connect(self._edit_selected_register_entry)
        self.resolve_register_btn.clicked.connect(self._toggle_resolve_register_entry)
        self.delete_register_btn.clicked.connect(self._delete_selected_register_entry)
        self.tabs.addTab(page, "Risks / issues")

    def _build_timeline_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        configure_box_layout(layout)
        section = SectionPanel(
            "Timeline",
            "Drag dated bars to reschedule tasks, milestones, and "
            "deliverables. Double-click a row to focus the related work.",
        )
        layout.addWidget(section, 1)
        self.timeline_summary = QLabel("Timeline needs dated tasks, milestones, or deliverables.")
        self.timeline_summary.setWordWrap(True)
        section.body_layout.addWidget(self.timeline_summary)

        self.timeline_widget = ProjectTimelineWidget(self)
        self.timeline_widget.rowActivated.connect(self._on_timeline_row_activated)
        self.timeline_widget.rescheduleRequested.connect(self.timelineRescheduleRequested.emit)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(260)
        scroll.setWidget(self.timeline_widget)
        self.timeline_stack = EmptyStateStack(
            scroll,
            "No timeline rows to show.",
            "Add start dates, due dates, milestones, or deliverables to build "
            "a project timeline.",
        )
        section.body_layout.addWidget(self.timeline_stack, 1)
        self.tabs.addTab(page, "Timeline")

    def _build_capacity_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        configure_box_layout(layout)
        summary_panel = SectionPanel(
            "Workload summary",
            "Watch day and week pressure before project commitments become unrealistic.",
        )
        layout.addWidget(summary_panel)

        summary_cards = QGridLayout()
        configure_box_layout(summary_cards, spacing=8)
        self.capacity_day_card = SummaryCard("Upcoming day buckets")
        self.capacity_week_card = SummaryCard("Upcoming week buckets")
        self.capacity_warning_card = SummaryCard("Workload warnings")
        summary_cards.addWidget(self.capacity_day_card, 0, 0)
        summary_cards.addWidget(self.capacity_week_card, 0, 1)
        summary_cards.addWidget(self.capacity_warning_card, 0, 2)
        summary_panel.body_layout.addLayout(summary_cards)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        day_panel = SectionPanel(
            "By day",
            "Near-term daily workload buckets for the selected project.",
        )
        self.day_table = self._make_table(
            ["Date", "Tasks", "Effort (min)", "High priority", "Overcommit"]
        )
        self.day_stack = EmptyStateStack(
            self.day_table,
            "No daily workload rows.",
            "Estimated effort, due dates, and milestones will populate the "
            "day workload view.",
        )
        day_panel.body_layout.addWidget(self.day_stack, 1)
        splitter.addWidget(day_panel)

        week_panel = SectionPanel(
            "By week",
            "Weekly capacity roll-up for the selected project.",
        )
        self.week_table = self._make_table(
            ["Week start", "Tasks", "Effort (min)", "High priority", "Overcommit"]
        )
        self.week_stack = EmptyStateStack(
            self.week_table,
            "No weekly workload rows.",
            "Weekly buckets appear when planned work has dates or effort.",
        )
        week_panel.body_layout.addWidget(self.week_stack, 1)
        splitter.addWidget(week_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.tabs.addTab(page, "Workload")

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        configure_data_table(
            table,
            min_height=220,
            max_height=300,
        )
        return table

    def _preferred_panel_height(self) -> int:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return 660
        available_height = int(screen.availableGeometry().height())
        return max(520, min(700, available_height - 140))

    def sizeHint(self) -> QSize:
        return QSize(860, self._preferred_panel_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(620, min(540, self._preferred_panel_height()))

    def _emit_project_change(self):
        project_id = self.project_combo.currentData()
        if project_id is None:
            return
        self.projectSelected.emit(int(project_id))

    def set_project_choices(self, projects: list[dict], current_project_id: int | None = None):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for row in projects or []:
            label = str(row.get("description") or row.get("project_name") or f"Project {row.get('id')}")
            self.project_combo.addItem(label, int(row.get("id")))
        if self.project_combo.count() > 0:
            idx = self.project_combo.findData(current_project_id) if current_project_id is not None else 0
            self.project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.project_combo.blockSignals(False)

    def set_dashboard(self, dashboard: dict | None):
        self._dashboard = dashboard or {}
        if not dashboard:
            self._current_project_id = None
            self.header_label.setText("No project selected")
            self.summary_health_card.set_value("-")
            self.summary_milestone_card.set_value("-")
            self.summary_blockers_card.set_value("-")
            self.summary_deliverables_card.set_value("-")
            self._clear_tables()
            return

        project = dashboard.get("project") or {}
        profile = dashboard.get("profile") or {}
        summary = dashboard.get("summary") or {}
        baseline = dashboard.get("baseline") or {}
        phases = dashboard.get("phases") or []
        milestones = dashboard.get("milestones") or []
        deliverables = dashboard.get("deliverables") or []
        register_entries = dashboard.get("register_entries") or []
        capacity = dashboard.get("capacity") or {}

        self._current_project_id = int(project.get("id")) if project.get("id") is not None else None
        self.header_label.setText(
            f"Project: {str(project.get('description') or '')} | "
            f"Owner: {str(profile.get('owner') or 'Self')} | "
            f"Category: {str(profile.get('category') or 'General')}"
        )
        self.summary_health_card.set_value(
            str(summary.get("effective_health_label") or "-"),
            str(summary.get("inferred_health_reason") or ""),
        )

        self.lbl_health.setText(
            f"{str(summary.get('effective_health_label') or '-')}"
            f" | Manual: {PROJECT_HEALTH_LABELS.get(str(summary.get('manual_health') or ''), 'automatic') if summary.get('manual_health') else 'automatic'}"
            f" | Inferred: {PROJECT_HEALTH_LABELS.get(str(summary.get('inferred_health') or ''), '-') }"
            f"\n{str(summary.get('inferred_health_reason') or '')}"
        )
        next_milestone = summary.get("next_milestone") or {}
        next_title = str(next_milestone.get("title") or "none")
        next_days = summary.get("next_milestone_days")
        next_suffix = "" if next_days is None else f" ({int(next_days)} day(s))"
        self.lbl_next_milestone.setText(next_title + next_suffix)
        self.summary_milestone_card.set_value(
            next_title,
            str(next_milestone.get("target_date") or next_suffix or ""),
        )
        self.lbl_blockers.setText(
            f"Tasks blocked: {int(summary.get('blocked_task_count') or 0)} | "
            f"Waiting: {int(summary.get('waiting_task_count') or 0)} | "
            f"Milestones blocked: {int(summary.get('blocked_milestone_count') or 0)}"
        )
        self.summary_blockers_card.set_value(
            str(int(summary.get("blocked_task_count") or 0)),
            (
                f"Waiting: {int(summary.get('waiting_task_count') or 0)} | "
                f"Milestones: {int(summary.get('blocked_milestone_count') or 0)}"
            ),
        )
        self.lbl_due_soon.setText(
            f"Overdue tasks: {int(summary.get('overdue_task_count') or 0)} | "
            f"Overdue milestones: {int(summary.get('milestone_overdue_count') or 0)} | "
            f"Deliverables due soon: {int(summary.get('deliverables_due_soon') or 0)}"
        )
        self.summary_deliverables_card.set_value(
            str(int(summary.get("deliverables_due_soon") or 0)),
            f"Overdue milestones: {int(summary.get('milestone_overdue_count') or 0)}",
        )
        self.lbl_effort.setText(
            f"Estimate: {int(summary.get('effort_estimate_minutes') or 0)} min | "
            f"Actual: {int(summary.get('effort_actual_minutes') or 0)} min | "
            f"Remaining: {int(summary.get('effort_remaining_minutes') or 0)} min"
        )
        self.lbl_variance.setText(str((summary.get("target_variance") or {}).get("label") or "No baseline"))

        self.objective_edit.setPlainText(str(profile.get("objective") or ""))
        self.scope_edit.setPlainText(str(profile.get("scope") or ""))
        self.out_of_scope_edit.setPlainText(str(profile.get("out_of_scope") or ""))
        self.owner_edit.setPlainText(str(profile.get("owner") or "Self"))
        self.stakeholders_edit.setPlainText(str(profile.get("stakeholders") or ""))
        self.target_date_edit.set_iso_date(profile.get("target_date"))
        self.success_criteria_edit.setPlainText(str(profile.get("success_criteria") or ""))
        health_idx = self.health_override_combo.findData(profile.get("project_status_health"))
        self.health_override_combo.setCurrentIndex(health_idx if health_idx >= 0 else 0)
        self.summary_edit.setPlainText(str(profile.get("summary") or ""))
        self.category_edit.setPlainText(str(profile.get("category") or ""))
        self.baseline_target_date.set_iso_date(baseline.get("target_date"))
        baseline_effort = baseline.get("effort_minutes")
        self.baseline_effort_spin.setValue(-1 if baseline_effort is None else max(-1, int(baseline_effort)))

        self.phases_list.clear()
        for row in phases:
            item = QListWidgetItem(str(row.get("name") or ""))
            item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
            self.phases_list.addItem(item)
        self.phases_stack.set_has_content(self.phases_list.count() > 0)

        self._populate_milestones_table(milestones)
        self._populate_deliverables_table(deliverables)
        self._populate_register_table(register_entries)
        timeline_rows = list(dashboard.get("timeline_rows") or [])
        self.timeline_widget.set_rows(timeline_rows)
        self.timeline_stack.set_has_content(bool(timeline_rows))
        self.timeline_summary.setText(
            f"{len(timeline_rows)} row(s) across tasks, milestones, and deliverables."
            if timeline_rows
            else "Timeline needs dated tasks, milestones, or deliverables."
        )
        self._populate_capacity(capacity)

    def _populate_milestones_table(self, milestones: list[dict]):
        self.milestones_table.setRowCount(0)
        for row in milestones:
            idx = self.milestones_table.rowCount()
            self.milestones_table.insertRow(idx)
            values = [
                str(row.get("title") or ""),
                str(row.get("phase_name") or ""),
                str(row.get("start_date") or ""),
                str(row.get("target_date") or ""),
                str(row.get("baseline_target_date") or ""),
                str(row.get("status") or ""),
                f"{int(row.get('progress_percent') or 0)}%",
                "Yes" if bool(row.get("is_blocked")) else "No",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
                self.milestones_table.setItem(idx, col, item)
        self.milestones_meta.setText(
            f"{len(milestones)} milestone(s) | "
            f"Blocked: {sum(1 for row in milestones if bool(row.get('is_blocked')))}"
        )
        self.milestones_stack.set_has_content(bool(milestones))
        header = self.milestones_table.horizontalHeader()
        for column in (1, 2, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _populate_deliverables_table(self, deliverables: list[dict]):
        self.deliverables_table.setRowCount(0)
        for row in deliverables:
            idx = self.deliverables_table.rowCount()
            self.deliverables_table.insertRow(idx)
            linked = str(row.get("linked_milestone_title") or row.get("linked_task_description") or "")
            values = [
                str(row.get("title") or ""),
                str(row.get("phase_name") or ""),
                str(row.get("due_date") or ""),
                str(row.get("baseline_due_date") or ""),
                str(row.get("status") or ""),
                str(row.get("version_ref") or ""),
                linked,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
                self.deliverables_table.setItem(idx, col, item)
        self.deliverables_meta.setText(
            f"{len(deliverables)} deliverable(s) | "
            f"Completed: {sum(1 for row in deliverables if str(row.get('status') or '') == 'completed')}"
        )
        self.deliverables_stack.set_has_content(bool(deliverables))
        header = self.deliverables_table.horizontalHeader()
        for column in (1, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

    def _populate_register_table(self, entries: list[dict]):
        self._all_register_entries = list(entries or [])
        self._refresh_register_table_only()

    def _refresh_register_table_only(self):
        entries = list(getattr(self, "_all_register_entries", []) or [])
        wanted = self.register_filter.currentData()
        if wanted:
            entries = [row for row in entries if str(row.get("entry_type") or "") == str(wanted)]
        self.register_table.setRowCount(0)
        for row in entries:
            idx = self.register_table.rowCount()
            self.register_table.insertRow(idx)
            linked_parts = []
            if row.get("linked_task_description"):
                linked_parts.append(str(row.get("linked_task_description")))
            if row.get("linked_milestone_title"):
                linked_parts.append(str(row.get("linked_milestone_title")))
            values = [
                str(row.get("entry_type") or ""),
                str(row.get("title") or ""),
                str(row.get("status") or ""),
                str(row.get("severity") or ""),
                str(row.get("review_date") or ""),
                ", ".join(linked_parts),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
                self.register_table.setItem(idx, col, item)
        self.register_meta.setText(f"{len(entries)} visible register item(s)")
        self.register_stack.set_has_content(bool(entries))
        header = self.register_table.horizontalHeader()
        for column in (0, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

    def _populate_capacity(self, capacity: dict):
        day_rows = list(capacity.get("days") or [])
        week_rows = list(capacity.get("weeks") or [])
        warnings = list(capacity.get("warnings") or [])
        self.capacity_day_card.set_value(str(len(day_rows)))
        self.capacity_week_card.set_value(str(len(week_rows)))
        self.capacity_warning_card.set_value(
            str(len(warnings)),
            str(warnings[0].get("message") or "") if warnings else "No pressure warnings.",
        )
        self.day_table.setRowCount(0)
        for row in day_rows:
            idx = self.day_table.rowCount()
            self.day_table.insertRow(idx)
            values = [
                str(row.get("date") or ""),
                str(int(row.get("task_count") or 0)),
                str(int(row.get("effort_minutes") or 0)),
                str(int(row.get("high_priority_count") or 0)),
                "Yes" if bool(row.get("overcommitted")) else "No",
            ]
            for col, value in enumerate(values):
                self.day_table.setItem(idx, col, QTableWidgetItem(value))
        self.day_stack.set_has_content(bool(day_rows))
        day_header = self.day_table.horizontalHeader()
        for column in range(self.day_table.columnCount()):
            day_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.week_table.setRowCount(0)
        for row in week_rows:
            idx = self.week_table.rowCount()
            self.week_table.insertRow(idx)
            values = [
                str(row.get("week_start") or ""),
                str(int(row.get("task_count") or 0)),
                str(int(row.get("effort_minutes") or 0)),
                str(int(row.get("high_priority_count") or 0)),
                "Yes" if bool(row.get("overcommitted")) else "No",
            ]
            for col, value in enumerate(values):
                self.week_table.setItem(idx, col, QTableWidgetItem(value))
        self.week_stack.set_has_content(bool(week_rows))
        week_header = self.week_table.horizontalHeader()
        for column in range(self.week_table.columnCount()):
            week_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    def _clear_tables(self):
        self.milestones_table.setRowCount(0)
        self.milestones_meta.setText("0 milestones")
        self.milestones_stack.set_has_content(False)
        self.deliverables_table.setRowCount(0)
        self.deliverables_meta.setText("0 deliverables")
        self.deliverables_stack.set_has_content(False)
        self.register_table.setRowCount(0)
        self.register_meta.setText("0 register entries")
        self.register_stack.set_has_content(False)
        self.timeline_widget.set_rows([])
        self.timeline_summary.setText("Timeline needs dated tasks, milestones, or deliverables.")
        self.timeline_stack.set_has_content(False)
        self.day_table.setRowCount(0)
        self.day_stack.set_has_content(False)
        self.week_table.setRowCount(0)
        self.week_stack.set_has_content(False)
        self.phases_list.clear()
        self.phases_stack.set_has_content(False)
        self.capacity_day_card.set_value("0")
        self.capacity_week_card.set_value("0")
        self.capacity_warning_card.set_value("0", "No pressure warnings.")

    def _selected_id_from_table(self, table: QTableWidget) -> int | None:
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        try:
            return int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            return None

    def _task_options(self) -> list[dict]:
        if not self._dashboard:
            return []
        return [row for row in (self._dashboard.get("tasks") or []) if int(row.get("id") or 0) != int(self._current_project_id or 0)]

    def _milestone_options(self, exclude_id: int | None = None) -> list[dict]:
        out = []
        for row in (self._dashboard or {}).get("milestones") or []:
            if exclude_id is not None and int(row.get("id") or 0) == int(exclude_id):
                continue
            out.append(row)
        return out

    def _phases(self) -> list[dict]:
        return list((self._dashboard or {}).get("phases") or [])

    def _emit_save_profile(self):
        if self._current_project_id is None:
            return
        payload = {
            "objective": self.objective_edit.toPlainText(),
            "scope": self.scope_edit.toPlainText(),
            "out_of_scope": self.out_of_scope_edit.toPlainText(),
            "owner": self.owner_edit.toPlainText().strip() or "Self",
            "stakeholders": self.stakeholders_edit.toPlainText(),
            "target_date": self.target_date_edit.iso_date(),
            "success_criteria": self.success_criteria_edit.toPlainText(),
            "project_status_health": self.health_override_combo.currentData(),
            "summary": self.summary_edit.toPlainText(),
            "category": self.category_edit.toPlainText(),
        }
        self.saveProfileRequested.emit(int(self._current_project_id), payload)

    def _emit_save_baseline(self):
        if self._current_project_id is None:
            return
        effort = int(self.baseline_effort_spin.value())
        self.saveBaselineRequested.emit(
            int(self._current_project_id),
            self.baseline_target_date.iso_date(),
            None if effort < 0 else effort,
        )

    def _selected_phase_id(self) -> int | None:
        item = self.phases_list.currentItem()
        if item is None:
            return None
        try:
            return int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            return None

    def _prompt_add_phase(self):
        if self._current_project_id is None:
            return
        name, ok = QInputDialog.getText(self, "Add phase", "Phase name:")
        if not ok:
            return
        phase_name = str(name or "").strip()
        if not phase_name:
            return
        self.addPhaseRequested.emit(int(self._current_project_id), phase_name)

    def _prompt_rename_phase(self):
        phase_id = self._selected_phase_id()
        item = self.phases_list.currentItem()
        if phase_id is None or item is None:
            return
        name, ok = QInputDialog.getText(self, "Rename phase", "Phase name:", text=item.text())
        if not ok:
            return
        phase_name = str(name or "").strip()
        if not phase_name:
            return
        self.renamePhaseRequested.emit(int(phase_id), phase_name)

    def _prompt_delete_phase(self):
        phase_id = self._selected_phase_id()
        item = self.phases_list.currentItem()
        if phase_id is None or item is None:
            return
        res = QMessageBox.warning(
            self,
            "Remove phase",
            f"Remove phase '{item.text()}'?\n\nAssigned tasks, milestones, and deliverables will lose the phase reference.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.deletePhaseRequested.emit(int(phase_id))

    def _add_milestone(self):
        if self._current_project_id is None:
            return
        dlg = MilestoneDialog(self._phases(), self._task_options(), self._milestone_options(), parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload.get("title"):
            return
        payload["project_task_id"] = int(self._current_project_id)
        self.addMilestoneRequested.emit(payload)

    def _edit_selected_milestone(self):
        milestone_id = self._selected_id_from_table(self.milestones_table)
        if milestone_id is None:
            return
        row = next((item for item in (self._dashboard or {}).get("milestones") or [] if int(item.get("id") or 0) == milestone_id), None)
        if row is None:
            return
        dlg = MilestoneDialog(
            self._phases(),
            self._task_options(),
            self._milestone_options(exclude_id=milestone_id),
            payload=row,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload.get("title"):
            return
        self.editMilestoneRequested.emit(int(milestone_id), payload)

    def _toggle_complete_milestone(self):
        milestone_id = self._selected_id_from_table(self.milestones_table)
        if milestone_id is None:
            return
        row = next((item for item in (self._dashboard or {}).get("milestones") or [] if int(item.get("id") or 0) == milestone_id), None)
        if row is None:
            return
        payload = dict(row)
        done = str(row.get("status") or "") != "completed"
        payload["status"] = "completed" if done else "planned"
        payload["progress_percent"] = 100 if done else 0
        payload["completed_at"] = date.today().isoformat() if done else None
        self.editMilestoneRequested.emit(int(milestone_id), payload)

    def _delete_selected_milestone(self):
        milestone_id = self._selected_id_from_table(self.milestones_table)
        if milestone_id is None:
            return
        res = QMessageBox.warning(
            self,
            "Delete milestone",
            "This milestone will be permanently removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.deleteMilestoneRequested.emit(int(milestone_id))

    def _add_deliverable(self):
        if self._current_project_id is None:
            return
        dlg = DeliverableDialog(self._phases(), self._task_options(), self._milestone_options(), parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload.get("title"):
            return
        payload["project_task_id"] = int(self._current_project_id)
        self.addDeliverableRequested.emit(payload)

    def _edit_selected_deliverable(self):
        deliverable_id = self._selected_id_from_table(self.deliverables_table)
        if deliverable_id is None:
            return
        row = next((item for item in (self._dashboard or {}).get("deliverables") or [] if int(item.get("id") or 0) == deliverable_id), None)
        if row is None:
            return
        dlg = DeliverableDialog(self._phases(), self._task_options(), self._milestone_options(), payload=row, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload.get("title"):
            return
        self.editDeliverableRequested.emit(int(deliverable_id), payload)

    def _toggle_complete_deliverable(self):
        deliverable_id = self._selected_id_from_table(self.deliverables_table)
        if deliverable_id is None:
            return
        row = next((item for item in (self._dashboard or {}).get("deliverables") or [] if int(item.get("id") or 0) == deliverable_id), None)
        if row is None:
            return
        payload = dict(row)
        done = str(row.get("status") or "") != "completed"
        payload["status"] = "completed" if done else "planned"
        payload["completed_at"] = date.today().isoformat() if done else None
        self.editDeliverableRequested.emit(int(deliverable_id), payload)

    def _delete_selected_deliverable(self):
        deliverable_id = self._selected_id_from_table(self.deliverables_table)
        if deliverable_id is None:
            return
        res = QMessageBox.warning(
            self,
            "Delete deliverable",
            "This deliverable will be permanently removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.deleteDeliverableRequested.emit(int(deliverable_id))

    def _add_register_entry(self):
        if self._current_project_id is None:
            return
        dlg = RegisterEntryDialog(self._task_options(), self._milestone_options(), parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload.get("title"):
            return
        payload["project_task_id"] = int(self._current_project_id)
        self.addRegisterEntryRequested.emit(payload)

    def _edit_selected_register_entry(self):
        entry_id = self._selected_id_from_table(self.register_table)
        if entry_id is None:
            return
        row = next((item for item in (self._dashboard or {}).get("register_entries") or [] if int(item.get("id") or 0) == entry_id), None)
        if row is None:
            return
        dlg = RegisterEntryDialog(self._task_options(), self._milestone_options(), payload=row, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload.get("title"):
            return
        self.editRegisterEntryRequested.emit(int(entry_id), payload)

    def _toggle_resolve_register_entry(self):
        entry_id = self._selected_id_from_table(self.register_table)
        if entry_id is None:
            return
        row = next((item for item in (self._dashboard or {}).get("register_entries") or [] if int(item.get("id") or 0) == entry_id), None)
        if row is None:
            return
        payload = dict(row)
        payload["status"] = "resolved" if str(row.get("status") or "") != "resolved" else "open"
        self.editRegisterEntryRequested.emit(int(entry_id), payload)

    def _delete_selected_register_entry(self):
        entry_id = self._selected_id_from_table(self.register_table)
        if entry_id is None:
            return
        res = QMessageBox.warning(
            self,
            "Delete register entry",
            "This register entry will be permanently removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.deleteRegisterEntryRequested.emit(int(entry_id))

    def _on_timeline_row_activated(self, kind: str, item_id: int):
        if kind == "task":
            self.focusTaskRequested.emit(int(item_id))
            return
        if kind == "project":
            self.focusTaskRequested.emit(int(item_id))
            return
        if kind == "milestone":
            row = next((item for item in (self._dashboard or {}).get("milestones") or [] if int(item.get("id") or 0) == int(item_id)), None)
            if row and row.get("linked_task_id"):
                self.focusTaskRequested.emit(int(row.get("linked_task_id")))
        if kind == "deliverable":
            row = next((item for item in (self._dashboard or {}).get("deliverables") or [] if int(item.get("id") or 0) == int(item_id)), None)
            if row and row.get("linked_task_id"):
                self.focusTaskRequested.emit(int(row.get("linked_task_id")))
