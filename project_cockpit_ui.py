from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
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
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from category_folders_ui import folder_display_name, folder_icon
from delegates import DateEditorWithClear
from context_help import attach_context_help, create_context_help_header
from gantt_ui import ProjectGanttView
from project_management import (
    DEFAULT_PHASE_NAMES,
    DELIVERABLE_STATUSES,
    MILESTONE_STATUSES,
    PROJECT_HEALTH_LABELS,
    PROJECT_HEALTH_STATES,
    REGISTER_ENTRY_TYPES,
    REGISTER_STATUSES,
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
    polish_button_layouts,
)


def _configure_wrapping_summary_label(label: QLabel) -> QLabel:
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Preferred,
    )
    label.setMinimumWidth(0)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


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
        polish_button_layouts(self)

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
        polish_button_layouts(self)
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
        polish_button_layouts(self)

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
        polish_button_layouts(self)

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


class ProjectCockpitPanel(QWidget):
    categorySelected = Signal(object)
    addCategoryRequested = Signal(object)
    editCategoryRequested = Signal(int)
    deleteCategoryRequested = Signal(int)
    projectSelected = Signal(int)
    saveProfileRequested = Signal(int, dict)
    saveBaselineRequested = Signal(int, object, object)
    addPhaseRequested = Signal(int, str)
    renamePhaseRequested = Signal(int, str)
    deletePhaseRequested = Signal(int)
    addTaskRequested = Signal(dict)
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
    archiveTaskRequested = Signal(int)
    deleteTaskRequested = Signal(int)
    timelineScheduleRequested = Signal(str, int, object, object)
    timelineDependencyEditRequested = Signal(str, int)
    editTaskDependenciesRequested = Signal(int, list)
    editMilestoneDependenciesRequested = Signal(int, list)
    timelineTaskMoveRelativeRequested = Signal(int, int)
    timelineTaskMoveRequested = Signal(int, object, int)
    timelineItemColorRequested = Signal(str, int, object)
    timelineItemColorResetRequested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_project_id: int | None = None
        self._dashboard: dict | None = None
        self._all_project_choices: list[dict] = []
        self._loading_dashboard = False
        self._last_profile_signature = None
        self._last_baseline_signature = None
        self._last_timeline_signature = None
        self._pending_timeline_dashboard: dict | None = None
        self._current_active_task_id: int | None = None
        self._profile_focus_widgets: set[QWidget] = set()
        self._baseline_focus_widgets: set[QWidget] = set()
        self._profile_save_timer = QTimer(self)
        self._profile_save_timer.setSingleShot(True)
        self._profile_save_timer.setInterval(0)
        self._profile_save_timer.timeout.connect(self._emit_save_profile)
        self._baseline_save_timer = QTimer(self)
        self._baseline_save_timer.setSingleShot(True)
        self._baseline_save_timer.setInterval(0)
        self._baseline_save_timer.timeout.connect(self._emit_save_baseline)
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
        self.category_combo = QComboBox()
        self.category_combo.setToolTip(
            "Filter project choices by category folder. Right-click for category actions."
        )
        self.category_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        nav_layout.addRow("Category", self.category_combo)
        self.project_combo = QComboBox()
        self.project_combo.setToolTip("Jump directly to a project context.")
        nav_layout.addRow("Project", self.project_combo)
        self.archive_project_btn = QPushButton("Archive project")
        self.archive_project_btn.setToolTip(
            "Archive the currently selected project root task and its subtree."
        )
        nav_panel.header_actions.addWidget(self.archive_project_btn)
        self.delete_project_btn = QPushButton("Delete permanently")
        self.delete_project_btn.setToolTip(
            "Permanently delete the currently selected project root task and its subtree."
        )
        nav_panel.header_actions.addWidget(self.delete_project_btn)
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
        self._install_auto_save_hooks()

        self.category_combo.currentIndexChanged.connect(self._emit_category_change)
        self.category_combo.customContextMenuRequested.connect(
            self._open_category_context_menu
        )
        self.project_combo.currentIndexChanged.connect(self._emit_project_change)
        self.project_combo.currentIndexChanged.connect(
            self._update_project_action_buttons
        )
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.archive_project_btn.clicked.connect(self._archive_current_project)
        self.delete_project_btn.clicked.connect(self._delete_current_project)
        polish_button_layouts(self)
        self._update_project_action_buttons()

    def focus_target(self) -> QWidget | None:
        tab_name = str(self.tabs.tabText(self.tabs.currentIndex()) or "").strip().lower()
        if tab_name == "milestones":
            return self.milestones_table
        if tab_name == "deliverables":
            return self.deliverables_table
        if tab_name == "risks / issues":
            return self.register_table
        if tab_name == "timeline":
            return self.timeline_widget.view
        if tab_name == "workload":
            return self.day_table
        return self.project_combo if self.project_combo.count() > 0 else self.category_combo

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
        configure_form_layout(summary_layout, label_width=150)
        summary_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.status_summary_layout = summary_layout
        self.lbl_health = _configure_wrapping_summary_label(QLabel("-"))
        self.lbl_next_milestone = _configure_wrapping_summary_label(QLabel("-"))
        self.lbl_blockers = _configure_wrapping_summary_label(QLabel("-"))
        self.lbl_due_soon = _configure_wrapping_summary_label(QLabel("-"))
        self.lbl_effort = _configure_wrapping_summary_label(QLabel("-"))
        self.lbl_variance = _configure_wrapping_summary_label(QLabel("-"))
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

        self.save_profile_btn.clicked.connect(self.request_immediate_profile_save)
        self.save_baseline_btn.clicked.connect(self.request_immediate_baseline_save)
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
        self.milestones_table.itemSelectionChanged.connect(
            self._sync_timeline_from_milestone_table
        )
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
        self.deliverables_table.itemSelectionChanged.connect(
            self._sync_timeline_from_deliverable_table
        )
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
        self.timeline_tab_page = page
        layout = QVBoxLayout(page)
        configure_box_layout(layout)
        section = SectionPanel(
            "Timeline",
            "Interactive project planner with hierarchy, dependencies, "
            "direct schedule editing, and zoomable time scales.",
        )
        layout.addWidget(section, 1)
        self.timeline_summary = QLabel("Timeline needs dated tasks, milestones, or deliverables.")
        self.timeline_summary.setWordWrap(True)
        section.body_layout.addWidget(self.timeline_summary)

        self.timeline_widget = ProjectGanttView(self)
        self.timeline_widget.recordSelected.connect(self._on_timeline_row_selected)
        self.timeline_widget.recordActivated.connect(self._on_timeline_row_activated)
        self.timeline_widget.scheduleEditRequested.connect(self.timelineScheduleRequested.emit)
        self.timeline_widget.dependencyEditRequested.connect(self._edit_timeline_dependencies)
        self.timeline_widget.taskCreateRequested.connect(self._add_task_from_timeline)
        self.timeline_widget.milestoneCreateRequested.connect(
            self._add_milestone_from_timeline
        )
        self.timeline_widget.deliverableCreateRequested.connect(
            self._add_deliverable_from_timeline
        )
        self.timeline_widget.taskMoveRequested.connect(self.timelineTaskMoveRequested.emit)
        self.timeline_widget.taskMoveRelativeRequested.connect(
            self.timelineTaskMoveRelativeRequested.emit
        )
        self.timeline_widget.itemColorChangeRequested.connect(
            self.timelineItemColorRequested.emit
        )
        self.timeline_widget.itemColorResetRequested.connect(
            self.timelineItemColorResetRequested.emit
        )
        self.timeline_widget.archiveTaskRequested.connect(
            self.archiveTaskRequested.emit
        )
        self.timeline_widget.deleteTaskRequested.connect(
            self.deleteTaskRequested.emit
        )
        self.archive_timeline_task_btn = QPushButton("Archive selected")
        self.archive_timeline_task_btn.setToolTip(
            "Archive the selected task or project row from the timeline."
        )
        section.header_actions.addWidget(self.archive_timeline_task_btn)
        self.delete_timeline_task_btn = QPushButton("Delete permanently")
        self.delete_timeline_task_btn.setToolTip(
            "Permanently delete the selected task or project row from the timeline."
        )
        section.header_actions.addWidget(self.delete_timeline_task_btn)
        self.timeline_stack = EmptyStateStack(
            self.timeline_widget,
            "No timeline rows to show.",
            "Add start dates, due dates, milestones, or deliverables to build "
            "a project timeline.",
        )
        section.body_layout.addWidget(self.timeline_stack, 1)
        self.archive_timeline_task_btn.clicked.connect(
            self._archive_selected_timeline_task
        )
        self.delete_timeline_task_btn.clicked.connect(
            self._delete_selected_timeline_task
        )
        self._update_timeline_action_buttons()
        self.tabs.addTab(page, "Timeline")

    def _timeline_tab_active(self) -> bool:
        return getattr(self, "timeline_tab_page", None) is not None and (
            self.tabs.currentWidget() is self.timeline_tab_page
        )

    @staticmethod
    def _timeline_signature(dashboard: dict | None):
        if not dashboard:
            return None
        timeline_rows = tuple(
            (
                str(row.get("uid") or ""),
                str(row.get("parent_uid") or ""),
                str(row.get("kind") or ""),
                str(row.get("label") or ""),
                str(row.get("phase_name") or ""),
                str(row.get("render_style") or ""),
                str(row.get("status") or ""),
                int(row.get("progress_percent") or 0),
                bool(row.get("blocked")),
                str(row.get("display_start_date") or row.get("start_date") or ""),
                str(row.get("display_end_date") or row.get("end_date") or ""),
                str(row.get("baseline_date") or ""),
                str(row.get("gantt_color_hex") or ""),
                int(row.get("sort_index") or 0),
            )
            for row in (dashboard.get("timeline_rows") or [])
        )
        dependencies = tuple(
            sorted(
                (
                    str(dep.get("predecessor_kind") or ""),
                    int(dep.get("predecessor_id") or 0),
                    str(dep.get("successor_kind") or ""),
                    int(dep.get("successor_id") or 0),
                    bool(dep.get("is_soft")),
                )
                for dep in (dashboard.get("dependencies") or [])
            )
        )
        return (timeline_rows, dependencies)

    def _apply_timeline_dashboard_if_needed(self):
        if self._pending_timeline_dashboard is None:
            return
        dashboard = self._pending_timeline_dashboard
        self._pending_timeline_dashboard = None
        self.timeline_widget.set_dashboard(dashboard)
        self.timeline_widget.set_active_task(self._current_active_task_id)

    def _on_current_tab_changed(self, _index: int):
        if self._timeline_tab_active():
            self._apply_timeline_dashboard_if_needed()
        self._update_timeline_action_buttons()

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
        self.flush_pending_saves()
        project_id = self.project_combo.currentData()
        if project_id is None:
            return
        self.projectSelected.emit(int(project_id))

    def _emit_category_change(self):
        folder_id = self.category_combo.currentData()
        self.categorySelected.emit(None if folder_id is None else int(folder_id))

    def _open_category_context_menu(self, pos):
        menu = QMenu(self)
        current_folder_id = self.category_combo.currentData()

        add_root = menu.addAction("Add category")
        add_root.triggered.connect(lambda: self.addCategoryRequested.emit(None))

        if current_folder_id is not None:
            add_child = menu.addAction("Add subcategory")
            add_child.triggered.connect(
                lambda: self.addCategoryRequested.emit(int(current_folder_id))
            )
            edit_act = menu.addAction("Customize category…")
            edit_act.triggered.connect(
                lambda: self.editCategoryRequested.emit(int(current_folder_id))
            )
            delete_act = menu.addAction("Delete category")
            delete_act.triggered.connect(
                lambda: self.deleteCategoryRequested.emit(int(current_folder_id))
            )
        menu.exec(self.category_combo.mapToGlobal(pos))

    def _install_auto_save_hooks(self):
        self._profile_focus_widgets = {
            self.objective_edit,
            self.scope_edit,
            self.out_of_scope_edit,
            self.owner_edit,
            self.stakeholders_edit,
            self.success_criteria_edit,
            self.summary_edit,
            self.category_edit,
        }
        self._baseline_focus_widgets = {self.baseline_effort_spin}
        for editor in self._profile_focus_widgets | self._baseline_focus_widgets:
            editor.installEventFilter(self)

        self.target_date_edit.date_edit.dateChanged.connect(self._schedule_profile_save)
        self.target_date_edit.clearRequested.connect(self._schedule_profile_save)
        self.health_override_combo.currentIndexChanged.connect(self._schedule_profile_save)
        self.baseline_target_date.date_edit.dateChanged.connect(self._schedule_baseline_save)
        self.baseline_target_date.clearRequested.connect(self._schedule_baseline_save)
        self.baseline_effort_spin.editingFinished.connect(self._schedule_baseline_save)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusOut:
            if watched in self._profile_focus_widgets:
                self._schedule_profile_save()
            elif watched in self._baseline_focus_widgets:
                self._schedule_baseline_save()
        return super().eventFilter(watched, event)

    def _collect_profile_payload(self) -> dict:
        return {
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

    @staticmethod
    def _profile_signature(payload: dict) -> tuple:
        return (
            str(payload.get("objective") or ""),
            str(payload.get("scope") or ""),
            str(payload.get("out_of_scope") or ""),
            str(payload.get("owner") or ""),
            str(payload.get("stakeholders") or ""),
            payload.get("target_date"),
            str(payload.get("success_criteria") or ""),
            payload.get("project_status_health"),
            str(payload.get("summary") or ""),
            str(payload.get("category") or ""),
        )

    def _collect_baseline_values(self) -> tuple[str | None, int | None]:
        effort = int(self.baseline_effort_spin.value())
        return (
            self.baseline_target_date.iso_date(),
            None if effort < 0 else effort,
        )

    @staticmethod
    def _baseline_signature(target_date: str | None, effort_minutes: int | None) -> tuple:
        return (target_date, effort_minutes)

    def _schedule_profile_save(self, *_):
        if self._loading_dashboard or self._current_project_id is None:
            return
        payload = self._collect_profile_payload()
        if self._profile_signature(payload) == self._last_profile_signature:
            return
        self._profile_save_timer.start()

    def _schedule_baseline_save(self, *_):
        if self._loading_dashboard or self._current_project_id is None:
            return
        target_date, effort_minutes = self._collect_baseline_values()
        if self._baseline_signature(target_date, effort_minutes) == self._last_baseline_signature:
            return
        self._baseline_save_timer.start()

    def request_immediate_profile_save(self):
        self._profile_save_timer.stop()
        self._emit_save_profile()

    def request_immediate_baseline_save(self):
        self._baseline_save_timer.stop()
        self._emit_save_baseline()

    def flush_pending_saves(self):
        self.request_immediate_profile_save()
        self.request_immediate_baseline_save()

    def mark_profile_saved(self, payload: dict):
        self._last_profile_signature = self._profile_signature(payload)

    def mark_baseline_saved(
        self,
        target_date: str | None,
        effort_minutes: int | None,
    ):
        self._last_baseline_signature = self._baseline_signature(
            target_date,
            effort_minutes,
        )

    def set_category_choices(
        self,
        folders: list[dict],
        current_folder_id: int | None = None,
    ):
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All categories", None)
        for row in folders or []:
            label = str(row.get("path") or folder_display_name(row) or "Category")
            self.category_combo.addItem(
                folder_icon(row.get("icon_name")),
                label,
                int(row.get("id")),
            )
        idx = (
            self.category_combo.findData(int(current_folder_id))
            if current_folder_id is not None
            else 0
        )
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_combo.blockSignals(False)

    def set_project_choices(self, projects: list[dict], current_project_id: int | None = None):
        self._all_project_choices = [dict(row) for row in (projects or [])]
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for row in self._all_project_choices:
            project_name = str(
                row.get("description") or row.get("project_name") or f"Project {row.get('id')}"
            )
            folder_path = str(row.get("folder_path") or "").strip()
            label = f"{folder_path} / {project_name}" if folder_path else project_name
            self.project_combo.addItem(
                folder_icon(row.get("folder_icon_name")),
                label,
                int(row.get("id")),
            )
        if self.project_combo.count() > 0:
            idx = self.project_combo.findData(current_project_id) if current_project_id is not None else 0
            self.project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.project_combo.blockSignals(False)

    def set_dashboard(self, dashboard: dict | None):
        self._profile_save_timer.stop()
        self._baseline_save_timer.stop()
        self._loading_dashboard = True
        self._dashboard = dashboard or {}
        if not dashboard:
            self._current_project_id = None
            self.header_label.setText("No project selected")
            self.summary_health_card.set_value("-")
            self.summary_milestone_card.set_value("-")
            self.summary_blockers_card.set_value("-")
            self.summary_deliverables_card.set_value("-")
            self._clear_tables()
            self._last_profile_signature = None
            self._last_baseline_signature = None
            self._last_timeline_signature = None
            self._pending_timeline_dashboard = None
            self._loading_dashboard = False
            self._update_project_action_buttons()
            self._update_timeline_action_buttons()
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
        self._last_profile_signature = self._profile_signature(
            self._collect_profile_payload()
        )
        target_date, effort_minutes = self._collect_baseline_values()
        self._last_baseline_signature = self._baseline_signature(
            target_date,
            effort_minutes,
        )

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
        timeline_signature = self._timeline_signature(dashboard)
        if self._timeline_tab_active():
            if timeline_signature != self._last_timeline_signature:
                self.timeline_widget.set_dashboard(dashboard)
                self._last_timeline_signature = timeline_signature
                self._pending_timeline_dashboard = None
        else:
            self.timeline_widget.prime_dashboard_data(dashboard)
            self._pending_timeline_dashboard = dashboard
            if timeline_signature == self._last_timeline_signature:
                self._pending_timeline_dashboard = None
        self.timeline_stack.set_has_content(bool(timeline_rows))
        self.timeline_summary.setText(
            f"{len(timeline_rows)} timeline row(s) across project structure, tasks, milestones, and deliverables."
            if timeline_rows
            else "Timeline needs dated tasks, milestones, or deliverables."
        )
        self._populate_capacity(capacity)
        self._loading_dashboard = False
        self._update_project_action_buttons()
        self._update_timeline_action_buttons()

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
        try:
            self.timeline_widget.set_dashboard(None)
        except RuntimeError:
            pass
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
        payload = self._collect_profile_payload()
        if self._profile_signature(payload) == self._last_profile_signature:
            return
        self.saveProfileRequested.emit(int(self._current_project_id), payload)

    def _emit_save_baseline(self):
        if self._current_project_id is None:
            return
        target_date, effort = self._collect_baseline_values()
        if self._baseline_signature(target_date, effort) == self._last_baseline_signature:
            return
        self.saveBaselineRequested.emit(
            int(self._current_project_id),
            target_date,
            effort,
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

    def _add_task_from_timeline(self, payload: dict):
        if self._current_project_id is None:
            return
        task_payload = dict(payload or {})
        task_payload["project_task_id"] = int(self._current_project_id)
        if not task_payload.get("description"):
            task_payload["description"] = "New task"
        self.addTaskRequested.emit(task_payload)

    def _add_milestone_from_timeline(self, payload: dict):
        if self._current_project_id is None:
            return
        initial_payload = dict(payload or {})
        initial_payload["project_task_id"] = int(self._current_project_id)
        dlg = MilestoneDialog(
            self._phases(),
            self._task_options(),
            self._milestone_options(),
            payload=initial_payload,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        milestone_payload = dlg.payload()
        if not milestone_payload.get("title"):
            return
        milestone_payload["project_task_id"] = int(self._current_project_id)
        self.addMilestoneRequested.emit(milestone_payload)

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

    def _add_deliverable_from_timeline(self, payload: dict):
        if self._current_project_id is None:
            return
        initial_payload = dict(payload or {})
        initial_payload["project_task_id"] = int(self._current_project_id)
        dlg = DeliverableDialog(
            self._phases(),
            self._task_options(),
            self._milestone_options(),
            payload=initial_payload,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        deliverable_payload = dlg.payload()
        if not deliverable_payload.get("title"):
            return
        deliverable_payload["project_task_id"] = int(self._current_project_id)
        self.addDeliverableRequested.emit(deliverable_payload)

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

    def _on_timeline_row_selected(self, kind: str, item_id: int):
        self._sync_tables_from_timeline(kind, item_id)
        self._focus_related_from_timeline(kind, item_id)
        self._update_timeline_action_buttons()

    def _on_timeline_row_activated(self, kind: str, item_id: int):
        self._sync_tables_from_timeline(kind, item_id)
        self._focus_related_from_timeline(kind, item_id)
        self._update_timeline_action_buttons()

    def _selected_timeline_task_id(self) -> int | None:
        row = self.timeline_widget._selected_row()
        if row is None:
            return None
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in {"task", "project"}:
            return None
        item_id = int(row.get("item_id") or 0)
        return item_id if item_id > 0 else None

    def _update_project_action_buttons(self):
        current_project_id = self.project_combo.currentData()
        if current_project_id is None:
            current_project_id = self._current_project_id
        enabled = current_project_id is not None and int(current_project_id) > 0
        self.archive_project_btn.setEnabled(enabled)
        self.delete_project_btn.setEnabled(enabled)

    def _update_timeline_action_buttons(self):
        enabled = self._selected_timeline_task_id() is not None
        if hasattr(self, "archive_timeline_task_btn"):
            self.archive_timeline_task_btn.setEnabled(enabled)
        if hasattr(self, "delete_timeline_task_btn"):
            self.delete_timeline_task_btn.setEnabled(enabled)

    def _archive_current_project(self):
        current_project_id = self.project_combo.currentData()
        if current_project_id is None:
            current_project_id = self._current_project_id
        if current_project_id is None:
            return
        self.archiveTaskRequested.emit(int(current_project_id))

    def _delete_current_project(self):
        current_project_id = self.project_combo.currentData()
        if current_project_id is None:
            current_project_id = self._current_project_id
        if current_project_id is None:
            return
        self.deleteTaskRequested.emit(int(current_project_id))

    def _archive_selected_timeline_task(self):
        task_id = self._selected_timeline_task_id()
        if task_id is None:
            return
        self.archiveTaskRequested.emit(int(task_id))

    def _delete_selected_timeline_task(self):
        task_id = self._selected_timeline_task_id()
        if task_id is None:
            return
        self.deleteTaskRequested.emit(int(task_id))

    def _select_row_by_id(self, table, item_id: int):
        target_id = int(item_id or 0)
        table.blockSignals(True)
        if target_id <= 0:
            table.clearSelection()
            table.blockSignals(False)
            return
        selected = False
        for row_index in range(table.rowCount()):
            item = table.item(row_index, 0)
            if item is None:
                continue
            if int(item.data(Qt.ItemDataRole.UserRole) or 0) == target_id:
                table.selectRow(row_index)
                table.scrollToItem(item, table.ScrollHint.PositionAtCenter)
                selected = True
                break
        if not selected:
            table.clearSelection()
        table.blockSignals(False)

    def _sync_tables_from_timeline(self, kind: str, item_id: int):
        item_kind = str(kind or "").strip().lower()
        if item_kind == "milestone":
            self._select_row_by_id(self.milestones_table, int(item_id))
            self.deliverables_table.blockSignals(True)
            self.deliverables_table.clearSelection()
            self.deliverables_table.blockSignals(False)
            return
        if item_kind == "deliverable":
            self._select_row_by_id(self.deliverables_table, int(item_id))
            self.milestones_table.blockSignals(True)
            self.milestones_table.clearSelection()
            self.milestones_table.blockSignals(False)
            return
        self.milestones_table.blockSignals(True)
        self.milestones_table.clearSelection()
        self.milestones_table.blockSignals(False)
        self.deliverables_table.blockSignals(True)
        self.deliverables_table.clearSelection()
        self.deliverables_table.blockSignals(False)

    def _sync_timeline_from_milestone_table(self):
        milestone_id = self._selected_id_from_table(self.milestones_table)
        if milestone_id is None:
            return
        self._apply_timeline_dashboard_if_needed()
        self.timeline_widget.select_item("milestone", int(milestone_id), ensure_visible=True)
        self._update_timeline_action_buttons()

    def _sync_timeline_from_deliverable_table(self):
        deliverable_id = self._selected_id_from_table(self.deliverables_table)
        if deliverable_id is None:
            return
        self._apply_timeline_dashboard_if_needed()
        self.timeline_widget.select_item(
            "deliverable",
            int(deliverable_id),
            ensure_visible=True,
        )
        self._update_timeline_action_buttons()

    def _focus_related_from_timeline(self, kind: str, item_id: int):
        item_kind = str(kind or "").strip().lower()
        if item_kind in {"task", "project"}:
            self.focusTaskRequested.emit(int(item_id))
            return
        if item_kind == "milestone":
            row = next(
                (
                    item
                    for item in (self._dashboard or {}).get("milestones") or []
                    if int(item.get("id") or 0) == int(item_id)
                ),
                None,
            )
            if row and row.get("linked_task_id"):
                self.focusTaskRequested.emit(int(row.get("linked_task_id")))
            elif row and row.get("project_task_id"):
                self.focusTaskRequested.emit(int(row.get("project_task_id")))
            return
        if item_kind == "deliverable":
            row = next(
                (
                    item
                    for item in (self._dashboard or {}).get("deliverables") or []
                    if int(item.get("id") or 0) == int(item_id)
                ),
                None,
            )
            if row and row.get("linked_task_id"):
                self.focusTaskRequested.emit(int(row.get("linked_task_id")))
            elif row and row.get("project_task_id"):
                self.focusTaskRequested.emit(int(row.get("project_task_id")))

    def _dependency_targets_for_milestone(self, milestone_id: int) -> list[dict]:
        return [
            {
                "kind": "task",
                "id": int(row.get("id") or 0),
                "label": f"Task: {str(row.get('description') or row.get('label') or '')}",
            }
            for row in self._task_options()
        ] + [
            {
                "kind": "milestone",
                "id": int(row.get("id") or 0),
                "label": f"Milestone: {str(row.get('title') or row.get('label') or '')}",
            }
            for row in self._milestone_options(exclude_id=milestone_id)
        ]

    def _edit_timeline_dependencies(self, kind: str, item_id: int):
        item_kind = str(kind or "").strip().lower()
        if item_kind == "task":
            row = next(
                (
                    item
                    for item in (self._dashboard or {}).get("tasks") or []
                    if int(item.get("id") or 0) == int(item_id)
                ),
                None,
            )
            if row is None:
                return
            targets = [
                {
                    "kind": "task",
                    "id": int(item.get("id") or 0),
                    "label": f"Task: {str(item.get('description') or '')}",
                }
                for item in self._task_options()
                if int(item.get("id") or 0) != int(item_id)
            ]
            selected_refs = [
                {"kind": "task", "id": int(dep.get("predecessor_id") or 0)}
                for dep in (self._dashboard or {}).get("dependencies") or []
                if str(dep.get("successor_kind") or "").strip().lower() == "task"
                and int(dep.get("successor_id") or 0) == int(item_id)
                and str(dep.get("predecessor_kind") or "").strip().lower() == "task"
                and int(dep.get("predecessor_id") or 0) > 0
            ]
            dlg = DependencyPickerDialog(targets, selected_refs, self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            refs = dlg.selected_refs()
            dep_ids = [
                int(ref.get("id") or 0)
                for ref in refs
                if str(ref.get("kind") or "").strip().lower() == "task"
            ]
            self.timelineDependencyEditRequested.emit("task", int(item_id))
            self.editTaskDependenciesRequested.emit(int(item_id), dep_ids)
            return
        if item_kind != "milestone":
            return
        row = next(
            (
                item
                for item in (self._dashboard or {}).get("milestones") or []
                if int(item.get("id") or 0) == int(item_id)
            ),
            None,
        )
        if row is None:
            return
        dlg = DependencyPickerDialog(
            self._dependency_targets_for_milestone(int(item_id)),
            row.get("dependencies") or [],
            self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        payload = dict(row)
        payload["dependencies"] = dlg.selected_refs()
        self.timelineDependencyEditRequested.emit("milestone", int(item_id))
        self.editMilestoneDependenciesRequested.emit(int(item_id), payload["dependencies"])

    def set_active_task(self, task_id: int | None):
        self._current_active_task_id = (
            None if task_id is None else int(task_id)
        )
        self.timeline_widget.set_active_task(task_id)
        self._update_timeline_action_buttons()
