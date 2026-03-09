import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# --- PyInstaller splash: close it ASAP (safe when not built with --splash) ---
try:
    import pyi_splash  # type: ignore
    pyi_splash.close()
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer, QModelIndex, QEvent, QDateTime, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QPushButton, QToolBar, QMenu, QMessageBox, QAbstractItemView,
    QLineEdit, QDockWidget, QLabel, QToolButton, QComboBox, QInputDialog,
    QFileDialog, QListWidget, QListWidgetItem, QUndoView, QScrollArea,
    QSystemTrayIcon,
    QGridLayout, QGroupBox, QSizePolicy, QLayout
)

from app_paths import app_db_path, app_data_dir
from app_metadata import (
    APP_NAME,
    APP_STORAGE_NAME,
    APP_STORAGE_ORGANIZATION,
    APP_VERSION,
    app_display_version,
)
from category_folders_ui import CategoryFolderDialog
from crash_logging import install_exception_hooks, log_event, log_exception
from db import Database, DatabaseMigrationError
from model import TaskTreeModel, STATUSES
from delegates import install_delegates
from settings_ui import SettingsDialog
from columns_ui import AddColumnDialog, RemoveColumnDialog
from filter_proxy import TaskFilterProxyModel
from filters_ui import FilterPanel
from capture_parsing import (
    BulkPostponeOverdueIntent,
    CreateRecurringTaskIntent,
    RescheduleSelectedIntent,
    ShowSearchIntent,
    TaskCaptureIntent,
    parse_capture_input,
)
from capture_actions import CaptureExecutionResult, execute_capture_intent
from details_panel import TaskDetailsPanel
from auto_backup import create_versioned_backup, rotate_backups
from help_ui import HelpDialog
from context_help import attach_context_help, create_context_help_header
from calendar_widgets import TaskCalendarWidget
from reminders_ui import ReminderBatchDialog
from archive_ui import ArchiveBrowserDialog
from command_palette import CommandPaletteDialog, PaletteCommand
from review_ui import PM_REVIEW_CATEGORIES, ReviewWorkflowPanel
from focus_ui import FocusPanel
from welcome_ui import WelcomeDialog
from demo_data import create_demo_workspace, populate_demo_database
from template_params import collect_template_placeholders, apply_template_values
from template_vars_ui import TemplateVariablesDialog
from analytics_ui import AnalyticsPanel
from diagnostics_ui import DiagnosticsDialog
from log_viewer_ui import LogViewerDialog
from quick_capture_ui import QuickCaptureDialog
from relationships_ui import RelationshipsPanel
from snapshot_history_ui import SnapshotHistoryDialog
from project_cockpit_ui import ProjectCockpitPanel
from platform_utils import shortcut_display_text, shortcut_sequence
from workspace_profiles import WorkspaceProfileManager
from workspace_ui import WorkspaceManagerDialog
from workflow_assist import (
    acknowledge_review_items,
    clear_review_acknowledgements,
    filter_acknowledged_review_data,
    review_ack_state_from_setting,
    review_ack_state_to_setting,
    should_show_onboarding,
)
from interaction_utils import WheelFocusGuard

from backup_io import export_backup_ui, import_backup_ui
from theme_io import export_themes_ui, import_themes_ui
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    configure_box_layout,
    configure_grid_layout,
)
from ui_perf import measure_ui


_UNSET = object()


class FloatingTaskTableWindow(QMainWindow):
    dockRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allow_close = False
        self.setObjectName("FloatingTaskTableWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def closeEvent(self, event):
        if self._allow_close:
            super().closeEvent(event)
            return
        self.dockRequested.emit()
        event.ignore()


class MainWindow(QMainWindow):
    REMINDER_MODE_NORMAL = "normal"
    REMINDER_MODE_MUTE_ALL = "mute_all"
    REMINDER_MODE_PRIORITY1_ONLY = "priority1_only"

    def __init__(self, workspace_manager: WorkspaceProfileManager | None = None, workspace_id: str | None = None):
        super().__init__()
        self.workspace_manager = workspace_manager or WorkspaceProfileManager()
        self.workspace = (
            self.workspace_manager.workspace_by_id(str(workspace_id or "").strip())
            or self.workspace_manager.current_workspace()
        )
        self.workspace_id = str(self.workspace.get("id") or "default")
        self.workspace_name = str(self.workspace.get("name") or self.workspace_id or "Default")
        self.workspace_db_path = str(self.workspace.get("db_path") or app_db_path())
        self.workspace_manager.ensure_workspace_state(self.workspace_id)
        self._workspace_switching = False
        self._closing_down = False
        self._replacement_window: MainWindow | None = None
        self._floating_table_window: FloatingTaskTableWindow | None = None
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            self.dockOptions()
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
            | QMainWindow.DockOption.AnimatedDocks
        )

        self.db = Database(self.workspace_db_path)
        self._update_window_title()

        # Source model (full tree)
        self.model = TaskTreeModel(self.db)
        self.undo_stack = self.model.undo_stack
        self._tooltips_enabled = True
        self._help_dialog: HelpDialog | None = None
        self._diagnostics_dialog: DiagnosticsDialog | None = None
        self._quick_capture_dialog: QuickCaptureDialog | None = None
        self._workspace_dialog: WorkspaceManagerDialog | None = None
        self._snapshot_dialog: SnapshotHistoryDialog | None = None
        self._log_viewer_dialog: LogViewerDialog | None = None
        self._tray_icon: QSystemTrayIcon | None = None
        self._global_capture_hotkey = None
        self._active_task_id: int | None = None
        self._active_task_details: dict | None = None
        self._row_action_update_pending = False
        self._row_action_state: tuple[int, int, int, int, bool] | None = None
        self._active_task_views_refresh_pending = False
        self._focus_panel_refresh_pending = False
        self._calendar_marker_refresh_pending = False
        self._review_panel_refresh_pending = False
        self._analytics_panel_refresh_pending = False
        self._project_panel_dirty = True
        self._project_panel_context_signature: tuple[int | None, int | None] | None = None
        self._reminder_mode = str(
            self.model.settings.value("ui/reminder_mode", self.REMINDER_MODE_NORMAL)
        ).strip() or self.REMINDER_MODE_NORMAL
        self._reminder_prompt_cooldown_until: datetime | None = None
        self._reminder_dialog_open = False
        app = QApplication.instance()
        self._wheel_focus_guard = WheelFocusGuard(self)
        if app is not None:
            app.installEventFilter(self._wheel_focus_guard)

        # Apply theme early so palette + fonts are correct
        self.model.apply_theme_to_app(QApplication.instance())
        icon = self.model.current_window_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        # Proxy (search + filters)
        self.proxy = TaskFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self._pending_edit_on_insert = False
        self.model.rowsInserted.connect(self._on_source_rows_inserted)

        self._perspectives = [
            ("All", "all"),
            ("Today", "today"),
            ("Upcoming", "upcoming"),
            ("Inbox", "inbox"),
            ("Someday", "someday"),
            ("Completed / Archive", "completed"),
        ]
        self._sort_modes = [
            ("Manual order", "manual"),
            ("Due date", "due_date"),
            ("Priority", "priority"),
            ("Status", "status"),
        ]

        # View
        self.view = QTreeView()
        self.view.setModel(self.proxy)
        self.view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setUniformRowHeights(False)
        self.view.setAllColumnsShowFocus(True)
        self.view.setTabKeyNavigation(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.view.setHorizontalScrollMode(QTreeView.ScrollMode.ScrollPerPixel)
        self.view.setVerticalScrollMode(QTreeView.ScrollMode.ScrollPerPixel)
        self.view.setAcceptDrops(True)
        self.view.viewport().setAcceptDrops(True)

        hdr = self.view.header()
        hdr.setSectionsMovable(True)
        hdr.setStretchLastSection(False)
        self._task_header_layout_pending = False
        self._task_header_layout_signature: tuple | None = None

        self.view.setRootIsDecorated(True)
        self.view.setItemsExpandable(True)
        self.view.setExpandsOnDoubleClick(True)
        self._row_action_gutter = 72

        # Default drag/drop enabled (will be disabled automatically when filters active)
        self._set_dragdrop_enabled(True)

        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._open_context_menu)

        # Persist collapse state (map proxy -> source)
        self._applying_expand_state = False
        self.view.collapsed.connect(self._on_collapsed)
        self.view.expanded.connect(self._on_expanded)

        install_delegates(self.view, self.proxy)

        # --- Quick add bar
        self.quick_add = QLineEdit()
        self.quick_add.setObjectName("QuickAddBar")
        self.quick_add.setPlaceholderText(
            f"Quick add... e.g. Call supplier @work next week !p1 /today ({shortcut_display_text('Ctrl+L')})"
        )
        self.quick_add.returnPressed.connect(self._quick_add_submit)

        self.view_mode = QComboBox()
        for title, key in self._perspectives:
            self.view_mode.addItem(title, key)
        self.view_mode.currentIndexChanged.connect(self._on_perspective_changed)

        self._perspective_buttons: dict[str, QToolButton] = {}
        self.perspective_bar = QWidget()
        perspective_bar_layout = QHBoxLayout(self.perspective_bar)
        configure_box_layout(perspective_bar_layout, margins=(0, 0, 0, 0), spacing=6)
        for title, key in self._perspectives:
            btn = QToolButton(self.perspective_bar)
            btn.setObjectName("PerspectiveNavButton")
            btn.setText(title)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setToolTip(f"Switch to the {title} perspective.")
            btn.clicked.connect(lambda _checked=False, k=key: self._set_perspective_by_key(k))
            self._perspective_buttons[key] = btn
            perspective_bar_layout.addWidget(btn)
        perspective_bar_layout.addStretch(1)

        self.sort_mode = QComboBox()
        for title, key in self._sort_modes:
            self.sort_mode.addItem(title, key)
        self.sort_mode.currentIndexChanged.connect(self._on_sort_mode_changed)

        control_h = max(26, self.fontMetrics().height() + 10)
        for w in (self.quick_add, self.view_mode, self.sort_mode):
            w.setMinimumHeight(control_h)
        for btn in self._perspective_buttons.values():
            btn.setMinimumHeight(control_h)

        # --- Search bar (above the view)
        self.search = QLineEdit()
        self.search.setObjectName("SearchBar")
        self.search.setPlaceholderText(
            f"Search… ({shortcut_display_text('Ctrl+F')})  status:todo priority:1 due<=today tag:work has:children"
        )
        self.search.textChanged.connect(self._on_search_changed)
        self.search.setMinimumHeight(control_h)

        clear_btn = QToolButton()
        clear_btn.setObjectName("SearchClear")
        clear_btn.setText("✕")
        clear_btn.setToolTip("Clear search")
        clear_btn.clicked.connect(lambda: self.search.setText(""))
        clear_btn.setMinimumHeight(control_h)

        controls_panel = QWidget()
        controls_panel.setObjectName("CaptureNavigationPanel")
        controls_layout = QVBoxLayout(controls_panel)
        configure_box_layout(controls_layout, spacing=10)

        capture_section = SectionPanel(
            "Quick add and search",
            "Capture new work, search the current dataset, and switch the "
            "active perspective without leaving the dock.",
        )
        self.capture_help_btn = attach_context_help(
            capture_section,
            "capture_and_search",
            self,
            tooltip="Open help for quick add and search",
        )
        controls_layout.addWidget(capture_section)

        top_layout = QGridLayout()
        configure_grid_layout(top_layout)
        quick_lbl = QLabel("Quick add")
        search_lbl = QLabel("Search")
        view_lbl = QLabel("View")
        sort_lbl = QLabel("Sort")
        for lbl in (quick_lbl, search_lbl, view_lbl, sort_lbl):
            lbl.setMinimumWidth(80)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        top_layout.addWidget(quick_lbl, 0, 0)
        top_layout.addWidget(self.quick_add, 0, 1)
        top_layout.addWidget(view_lbl, 0, 2)
        top_layout.addWidget(self.view_mode, 0, 3)
        top_layout.addWidget(sort_lbl, 0, 4)
        top_layout.addWidget(self.sort_mode, 0, 5)
        top_layout.addWidget(search_lbl, 1, 0)
        top_layout.addWidget(self.search, 1, 1, 1, 4)
        top_layout.addWidget(clear_btn, 1, 5)
        top_layout.setColumnStretch(1, 1)
        top_layout.setColumnStretch(3, 0)
        top_layout.setColumnStretch(5, 0)
        capture_section.body_layout.addLayout(top_layout)

        navigation_section = SectionPanel(
            "Perspectives",
            "Keep major views visible as first-class navigation targets and "
            "switch them without hunting through menus.",
        )
        self.perspectives_help_btn = attach_context_help(
            navigation_section,
            "perspectives",
            self,
            tooltip="Open help for perspectives and views",
        )
        controls_layout.addWidget(navigation_section)
        navigation_section.body_layout.addWidget(self.perspective_bar)
        self.controls_panel = controls_panel

        controls_scroll = QScrollArea()
        controls_scroll.setObjectName("CaptureNavigationScroll")
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        controls_scroll.setWidget(self.controls_panel)
        controls_scroll.setMaximumHeight((control_h * 4) + 148)
        self.controls_scroll = controls_scroll

        self._row_gutter = QWidget()
        self._row_gutter.setObjectName("RowActionGutter")
        self._row_gutter.setFixedWidth(self._row_action_gutter)

        tree_row = QHBoxLayout()
        tree_row.setContentsMargins(0, 0, 0, 0)
        tree_row.setSpacing(0)
        tree_row.addWidget(self._row_gutter)
        tree_row.addWidget(self.view, 1)

        self.tree_wrap = QWidget()
        self.tree_wrap.setObjectName("TaskTableContainer")
        self.tree_wrap.setLayout(tree_row)

        main = QWidget()
        main.setObjectName("MainTreeHost")
        v = QVBoxLayout(main)
        configure_box_layout(v, margins=(8, 8, 8, 8), spacing=8)
        self._task_workspace_header = create_context_help_header(
            "Task workspace",
            "main_task_workspace",
            self,
            tooltip="Open help for the task workspace",
        )
        v.addWidget(self._task_workspace_header)
        self._table_placeholder = QLabel(
            "Task table is floating in a separate window.\nUse View > Float task table to dock it back."
        )
        self._table_placeholder.setObjectName("TaskTableFloatingPlaceholder")
        self._table_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table_placeholder.setWordWrap(True)
        self._table_placeholder.hide()
        v.addWidget(self._table_placeholder, 1)
        v.addWidget(self.tree_wrap, 1)
        self._table_host_layout = v
        self.setCentralWidget(main)

        # --- Row overlay buttons (+ / -) ---
        self.row_add_btn = QToolButton(self._row_gutter)
        self.row_add_btn.setObjectName("RowAddChildButton")
        self.row_add_btn.setText("+")
        self.row_add_btn.setToolTip("Add child task to this row")
        self.row_add_btn.clicked.connect(self._row_add_child_clicked)
        self.row_add_btn.hide()

        self.row_del_btn = QToolButton(self._row_gutter)
        self.row_del_btn.setObjectName("RowDeleteButton")
        self.row_del_btn.setText("–")
        self.row_del_btn.setToolTip("Archive this task")
        self.row_del_btn.clicked.connect(self._row_delete_clicked)
        self.row_del_btn.hide()

        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.view.verticalScrollBar().valueChanged.connect(
            lambda *_: self._schedule_row_action_button_update()
        )
        self.view.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._schedule_row_action_button_update()
        )
        self.view.header().geometriesChanged.connect(
            lambda: self._schedule_row_action_button_update()
        )
        self.view.viewport().installEventFilter(self)
        self.view.installEventFilter(self)
        self.view.header().installEventFilter(self)

        self._init_controls_dock()
        # Advanced filter panel (dock)
        self._init_filter_dock()
        self._init_details_dock()
        self._init_project_dock()
        self._init_relationships_dock()
        self._init_undo_history_dock()
        self._init_focus_dock()
        self._init_calendar_dock()
        self._init_review_dock()
        self._init_analytics_dock()

        self._build_menus_and_toolbar()
        self._init_quick_capture_tools()
        self._init_status_bar()
        self._apply_widget_tooltips()
        self._apply_accessibility_metadata()
        self._restore_ui_settings()
        tooltips_enabled = self.model.settings.value("ui/tooltips_enabled", True, type=bool)
        self._set_tooltips_enabled(bool(tooltips_enabled), show_message=False)

        self.model.modelReset.connect(self._apply_collapsed_state_to_view)
        self.proxy.modelReset.connect(self._apply_collapsed_state_to_view)
        self.model.modelReset.connect(self._refresh_calendar_list)
        self.model.modelReset.connect(self._schedule_calendar_marker_refresh)
        self.model.modelReset.connect(self._schedule_review_panel_refresh)
        self.model.modelReset.connect(self._schedule_focus_panel_refresh)
        self.model.modelReset.connect(self._schedule_analytics_panel_refresh)
        self.model.modelReset.connect(self._schedule_active_task_view_refresh)
        self.proxy.modelReset.connect(self._schedule_active_task_view_refresh)
        self.model.modelReset.connect(self._schedule_task_header_layout)
        self.proxy.modelReset.connect(self._schedule_task_header_layout)
        self.model.modelReset.connect(self._mark_project_panel_dirty)
        self.proxy.modelReset.connect(self._mark_project_panel_dirty)
        self.model.dataChanged.connect(lambda *_: self._schedule_calendar_marker_refresh())
        self.model.dataChanged.connect(lambda *_: self._schedule_focus_panel_refresh())
        self.model.dataChanged.connect(lambda *_: self._schedule_active_task_view_refresh())
        self.model.dataChanged.connect(self._mark_project_panel_dirty)
        self.model.rowsInserted.connect(lambda *_: self._schedule_calendar_marker_refresh())
        self.model.rowsInserted.connect(lambda *_: self._schedule_focus_panel_refresh())
        self.model.rowsInserted.connect(lambda *_: self._schedule_active_task_view_refresh())
        self.model.rowsInserted.connect(self._mark_project_panel_dirty)
        self.model.rowsRemoved.connect(lambda *_: self._schedule_calendar_marker_refresh())
        self.model.rowsRemoved.connect(lambda *_: self._schedule_focus_panel_refresh())
        self.model.rowsRemoved.connect(lambda *_: self._schedule_active_task_view_refresh())
        self.model.rowsRemoved.connect(self._mark_project_panel_dirty)
        self.undo_stack.indexChanged.connect(self._on_undo_stack_index_changed)

        # Timer to refresh due-date gradient + foreground contrast
        self._due_timer = QTimer(self)
        self._due_timer.setInterval(60_000)
        self._due_timer.timeout.connect(self.model.refresh_due_highlights)
        self._due_timer.start()

        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(30_000)
        self._reminder_timer.timeout.connect(self._poll_reminders)
        self._reminder_timer.start()

        self._auto_backup_timer = QTimer(self)
        self._auto_backup_timer.timeout.connect(self._run_auto_backup)
        self._configure_auto_backup_timer()

        self.model.refresh_due_highlights()

        # Shortcut: focus search
        focus_search = QAction(self)
        focus_search.setShortcut(shortcut_sequence("Ctrl+F"))
        focus_search.triggered.connect(self._focus_search_input)
        self.addAction(focus_search)

        focus_quick_add = QAction(self)
        focus_quick_add.setShortcut(shortcut_sequence("Ctrl+L"))
        focus_quick_add.triggered.connect(self._focus_quick_add_input)
        self.addAction(focus_quick_add)

        QTimer.singleShot(0, self._schedule_row_action_button_update)
        QTimer.singleShot(0, self._schedule_task_header_layout)
        QTimer.singleShot(0, self._schedule_active_task_view_refresh)
        QTimer.singleShot(0, self._maybe_show_onboarding)

    # ---------- Splash (close again once UI shows) ----------
    def showEvent(self, event):
        super().showEvent(event)
        self._apply_task_header_layout(force=True)
        self._schedule_row_action_button_update()
        try:
            import pyi_splash  # type: ignore
            pyi_splash.close()
        except Exception:
            pass

    # ---------- Event filter for overlay alignment ----------
    def eventFilter(self, obj, event):
        with measure_ui("main.eventFilter"):
            if event.type() == QEvent.Type.ToolTip and not self._tooltips_enabled:
                return True
            if hasattr(self, "view") and obj in (self.view, self.view.viewport()) and event.type() == QEvent.Type.KeyPress:
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                        if self.view.state() != QAbstractItemView.State.EditingState and self.view.currentIndex().isValid():
                            self._edit_current_cell()
                            return True
            if hasattr(self, "view") and obj in (self.view.viewport(), self.view):
                if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                    self._schedule_row_action_button_update()
            if hasattr(self, "view") and obj in (self.view, self.view.header()):
                if event.type() in (
                    QEvent.Type.Show,
                    QEvent.Type.Resize,
                    QEvent.Type.FontChange,
                    QEvent.Type.StyleChange,
                ):
                    self._schedule_task_header_layout()
            if hasattr(self, "view") and obj == self.view.viewport():
                if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                    md = event.mimeData()
                    if md and md.hasUrls():
                        event.acceptProposedAction()
                        return True
                if event.type() == QEvent.Type.Drop:
                    md = event.mimeData()
                    if md and md.hasUrls():
                        tid = self._selected_task_id()
                        if tid is not None:
                            paths = []
                            for u in md.urls():
                                if u.isLocalFile():
                                    p = u.toLocalFile()
                                    if p:
                                        paths.append(p)
                            if paths:
                                self.model.undo_stack.beginMacro("Attach dropped files")
                                try:
                                    for p in paths:
                                        try:
                                            self.model.add_attachment(int(tid), p, "")
                                        except Exception:
                                            continue
                                finally:
                                    self.model.undo_stack.endMacro()
                                self._refresh_details_dock()
                        event.acceptProposedAction()
                        return True
            return super().eventFilter(obj, event)

    def _row_button_size(self) -> int:
        h = self.view.fontMetrics().height()
        return max(18, min(28, h + 6))

    def _schedule_row_action_button_update(self):
        if self._row_action_update_pending:
            return
        self._row_action_update_pending = True
        QTimer.singleShot(16, self._flush_row_action_button_update)

    def _flush_row_action_button_update(self):
        self._row_action_update_pending = False
        self._update_row_action_buttons()

    def _update_row_action_buttons(self):
        with measure_ui(
            "main._update_row_action_buttons",
            visible=bool(self._is_task_table_visible()),
        ):
            self._update_row_action_buttons_impl()

    def _update_row_action_buttons_impl(self):
        if not getattr(self, "tree_wrap", None) or not self._is_task_table_visible():
            self._row_action_state = None
            self.row_add_btn.hide()
            self.row_del_btn.hide()
            return
        idx = self.view.currentIndex()
        if not idx.isValid():
            self._row_action_state = None
            self.row_add_btn.hide()
            self.row_del_btn.hide()
            return

        idx0 = idx.siblingAtColumn(0)
        rect = self.view.visualRect(idx0)
        vp_rect = self.view.viewport().rect()

        if rect.isNull() or rect.height() <= 0 or not rect.intersects(vp_rect):
            self._row_action_state = None
            self.row_add_btn.hide()
            self.row_del_btn.hide()
            return

        size = self._row_button_size()
        gap = 6
        required_gutter = (2 * size) + gap + 8
        if self._row_action_gutter < required_gutter:
            self._row_action_gutter = required_gutter
            self._row_gutter.setFixedWidth(self._row_action_gutter)
        gutter_w = self._row_gutter.width()

        self.row_add_btn.setFixedSize(size, size)
        self.row_del_btn.setFixedSize(size, size)

        src_idx0 = self.proxy.mapToSource(idx0)
        task_id = self.model.task_id_from_index(src_idx0)
        if task_id is None:
            self._row_action_state = None
            self.row_add_btn.hide()
            self.row_del_btn.hide()
            return
        can_add_child = task_id is not None and self.model.can_add_child_task(task_id)
        self.row_add_btn.setEnabled(can_add_child)
        if can_add_child:
            self.row_add_btn.setToolTip("Add child task to this row")
        else:
            self.row_add_btn.setToolTip(
                f"Max nesting depth ({self.model.max_nesting_levels()}) reached for this branch"
            )

        # center two buttons within the dedicated left gutter
        x_add = max(4, (gutter_w - ((2 * size) + gap)) // 2)
        x_del = x_add + size + gap

        center_global = self.view.viewport().mapToGlobal(rect.center())
        center_in_gutter = self._row_gutter.mapFromGlobal(center_global)
        y = center_in_gutter.y() - (size // 2)
        y = max(0, min(self._row_gutter.height() - size, y))

        state = (x_add, y, x_del, y, bool(can_add_child))
        if self._row_action_state != state:
            self.row_add_btn.move(x_add, y)
            self.row_del_btn.move(x_del, y)
            self.row_add_btn.setEnabled(can_add_child)
            self._row_action_state = state

        if not self.row_add_btn.isVisible():
            self.row_add_btn.show()
            self.row_add_btn.raise_()
        if not self.row_del_btn.isVisible():
            self.row_del_btn.show()
            self.row_del_btn.raise_()

    def _row_add_child_clicked(self):
        pidx = self.view.currentIndex()
        if not pidx.isValid():
            return
        src = self.proxy.mapToSource(pidx)
        task_id = self.model.task_id_from_index(src)
        if task_id is None:
            return
        self.view.expand(pidx)
        if not self.model.add_child_task(task_id):
            self._pending_edit_on_insert = False
            self._show_nesting_limit_message()
        self._schedule_row_action_button_update()

    def _row_delete_clicked(self):
        self._archive_selected()
        self._schedule_row_action_button_update()

    def _request_edit_after_insert(self):
        self._pending_edit_on_insert = True

    def _show_nesting_limit_message(self):
        max_depth = self.model.max_nesting_levels()
        QMessageBox.information(
            self,
            "Nesting limit reached",
            f"A branch can be nested at most {max_depth} levels below a top-level parent.",
        )

    def _on_source_rows_inserted(self, parent: QModelIndex, first: int, last: int):
        if not self._pending_edit_on_insert:
            return

        self._pending_edit_on_insert = False

        # Focus the first column of the last inserted row
        src_idx = self.model.index(last, 0, parent)
        if not src_idx.isValid():
            return

        proxy_idx = self.proxy.mapFromSource(src_idx)
        if not proxy_idx.isValid():
            return

        # Ensure visible and selected
        if parent.isValid():
            parent_proxy = self.proxy.mapFromSource(parent)
            if parent_proxy.isValid():
                self.view.expand(parent_proxy)

        self.view.setCurrentIndex(proxy_idx)
        self.view.scrollTo(proxy_idx)

        QTimer.singleShot(0, lambda: self.view.edit(proxy_idx))

    def _add_task_and_edit(self):
        self._request_edit_after_insert()
        if not self.model.add_task(parent_id=None):
            self._pending_edit_on_insert = False

    def _capture_default_bucket(self, source: str = "quick_add") -> str:
        source_key = str(source or "quick_add").strip().lower()
        if source_key in {"global", "tray", "capture_dialog"}:
            return "inbox"
        perspective = str(self.view_mode.currentData() or "all")
        return perspective if perspective in {"inbox", "today", "upcoming", "someday"} else "inbox"

    def _submit_capture_text(self, raw: str, *, default_bucket: str) -> CaptureExecutionResult:
        try:
            intent = parse_capture_input(raw)
            return execute_capture_intent(intent, self, default_bucket=default_bucket)
        except Exception as e:
            log_exception(e, context="quick-capture", db_path=self.db.path)
            return CaptureExecutionResult(False, "Capture failed unexpectedly. Check Diagnostics/Logs for details.")

    def _quick_add_submit(self):
        raw = self.quick_add.text().strip()
        if not raw:
            return
        result = self._submit_capture_text(raw, default_bucket=self._capture_default_bucket("quick_add"))
        if result.success:
            self.quick_add.clear()
        if result.message:
            self.statusBar().showMessage(result.message, 4000)
        self.quick_add.setFocus()

    def _resolve_parent_hint_task_id(self, hint: str) -> int | None:
        raw = str(hint or "").strip()
        if not raw:
            return None
        lowered = raw.lower()
        if lowered in {"parent", "selected", "current"}:
            return self._selected_task_id()
        try:
            task_id = int(raw)
        except Exception:
            task_id = None
        if task_id is not None and self.model.node_for_id(int(task_id)):
            return int(task_id)

        exact_matches: list[int] = []
        contains_matches: list[int] = []
        for node in self.model.iter_nodes_preorder():
            if not node.task or str(node.task.get("archived_at") or "").strip():
                continue
            desc = str(node.task.get("description") or "").strip()
            if not desc:
                continue
            task_id = int(node.task["id"])
            desc_lower = desc.lower()
            if desc_lower == lowered:
                exact_matches.append(task_id)
            elif lowered in desc_lower:
                contains_matches.append(task_id)
        if exact_matches:
            return int(exact_matches[0])
        if contains_matches:
            return int(contains_matches[0])
        return None

    def _resolve_capture_parent_id(self, parsed) -> tuple[int | None, list[str]]:
        notes: list[str] = []
        parent_id = None
        if str(parsed.parent_hint or "").strip():
            parent_id = self._resolve_parent_hint_task_id(str(parsed.parent_hint))
            if parent_id is None:
                notes.append(f"Parent '{parsed.parent_hint}' was not found; captured as top-level.")
        elif bool(parsed.create_as_child):
            parent_id = self._selected_task_id()
            if parent_id is None:
                notes.append("No current row selected; captured as top-level.")
        return parent_id, notes

    def _set_due_date_for_task_ids(self, task_ids: list[int], due_text: str | None, macro_text: str) -> int:
        due_col = self._column_index_for_key("due_date")
        if due_col is None:
            return 0
        changed = 0
        self.model.undo_stack.beginMacro(str(macro_text or "Set due date"))
        try:
            for tid in {int(x) for x in task_ids if int(x) > 0}:
                src = self._source_index_for_task_id(int(tid), due_col)
                if not src.isValid():
                    continue
                self.model.setData(src, due_text, Qt.ItemDataRole.EditRole)
                changed += 1
        finally:
            self.model.undo_stack.endMacro()
        return changed

    def _shift_due_dates_for_task_ids(self, task_ids: list[int], delta_days: int, macro_text: str) -> int:
        changed = 0
        due_col = self._column_index_for_key("due_date")
        if due_col is None:
            return 0
        self.model.undo_stack.beginMacro(str(macro_text or "Shift due date"))
        try:
            for tid in {int(x) for x in task_ids if int(x) > 0}:
                node = self.model.node_for_id(int(tid))
                if not node or not node.task:
                    continue
                due = str(node.task.get("due_date") or "").strip()
                if not due:
                    continue
                try:
                    shifted = datetime.strptime(due[:10], "%Y-%m-%d").date() + timedelta(days=int(delta_days))
                except Exception:
                    continue
                src = self._source_index_for_task_id(int(tid), due_col)
                if not src.isValid():
                    continue
                self.model.setData(src, shifted.isoformat(), Qt.ItemDataRole.EditRole)
                changed += 1
        finally:
            self.model.undo_stack.endMacro()
        return changed

    def _show_main_window(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def handle_task_capture(self, intent: TaskCaptureIntent, default_bucket: str) -> CaptureExecutionResult:
        parsed = intent.parsed
        description = str(parsed.description or "").strip()
        if not description:
            return CaptureExecutionResult(False, "Nothing to capture.")

        parent_id, notes = self._resolve_capture_parent_id(parsed)
        bucket = str(parsed.bucket or default_bucket or "inbox").strip().lower() or "inbox"
        ok = self.model.add_task_with_values(
            description=description,
            due_date=parsed.due_date,
            priority=parsed.priority,
            parent_id=parent_id,
            planned_bucket=bucket,
            tags=list(parsed.tags or []),
        )
        if not ok:
            return CaptureExecutionResult(False, "Capture failed. Nesting limit reached for the target parent.")

        new_id = self.model.last_added_task_id()
        if self.isVisible() and new_id is not None:
            before = self._selected_task_id()
            self._focus_task_by_id(int(new_id))
            after = self._selected_task_id()
            if after == int(new_id) and before != after:
                self._refresh_details_dock()
            elif after != int(new_id):
                notes.append("Created task is hidden by the current view or filter.")
        message = f"Captured to {bucket}."
        if notes or parsed.parse_warnings:
            message = f"{message} {' '.join(notes + list(parsed.parse_warnings))}".strip()
        return CaptureExecutionResult(True, message)

    def handle_reschedule_selected(self, intent: RescheduleSelectedIntent) -> CaptureExecutionResult:
        task_id = self._selected_task_id()
        if task_id is None:
            return CaptureExecutionResult(False, "Select a task before using move-this planning commands.")
        changed = self._set_due_date_for_task_ids([int(task_id)], intent.due_date, "Move selected task")
        if changed <= 0:
            return CaptureExecutionResult(False, "Selected task could not be rescheduled.")
        self._focus_task_by_id(int(task_id))
        return CaptureExecutionResult(True, f"Moved selected task to {intent.due_date}.")

    def handle_bulk_postpone_overdue(self, intent: BulkPostponeOverdueIntent) -> CaptureExecutionResult:
        tag_filter = str(intent.tag or "").strip().lower() or None
        today = date.today()
        matches: list[int] = []
        for task in self.db.fetch_tasks():
            if str(task.get("archived_at") or "").strip():
                continue
            if str(task.get("status") or "") == "Done":
                continue
            due = str(task.get("due_date") or "").strip()
            if not due:
                continue
            try:
                due_date = datetime.strptime(due[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if due_date >= today:
                continue
            if tag_filter:
                tags = {str(t).strip().lower() for t in (task.get("tags") or []) if str(t).strip()}
                if tag_filter not in tags:
                    continue
            matches.append(int(task["id"]))

        if not matches:
            label = f"tag '{tag_filter}' " if tag_filter else ""
            return CaptureExecutionResult(False, f"No overdue {label}tasks matched that command.")

        label = f"tag '{tag_filter}' " if tag_filter else ""
        answer = QMessageBox.question(
            self,
            "Confirm postpone",
            f"Postpone {len(matches)} overdue {label}task(s) by {int(intent.days)} day(s)?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return CaptureExecutionResult(False, "Bulk postpone cancelled.")

        changed = self._shift_due_dates_for_task_ids(matches, int(intent.days), "Postpone overdue tasks")
        if changed <= 0:
            return CaptureExecutionResult(False, "No due dates were changed.")
        self._refresh_calendar_list()
        return CaptureExecutionResult(True, f"Postponed {changed} overdue task(s) by {int(intent.days)} day(s).")

    def handle_show_search(self, intent: ShowSearchIntent) -> CaptureExecutionResult:
        if intent.perspective:
            self._set_perspective_by_key(str(intent.perspective))
        self.search.setText(str(intent.query_text or ""))
        self._show_main_window()
        self.search.setFocus()
        return CaptureExecutionResult(True, f"Showing results for {intent.query_text}.")

    def handle_create_recurring(self, intent: CreateRecurringTaskIntent, default_bucket: str) -> CaptureExecutionResult:
        parsed = intent.parsed
        description = str(parsed.description or "").strip()
        if not description:
            return CaptureExecutionResult(False, "Recurring capture requires a task description.")
        parent_id, notes = self._resolve_capture_parent_id(parsed)
        bucket = str(parsed.bucket or default_bucket or "inbox").strip().lower() or "inbox"
        self.model.undo_stack.beginMacro("Create recurring task")
        try:
            ok = self.model.add_task_with_values(
                description=description,
                due_date=intent.due_date,
                priority=parsed.priority,
                parent_id=parent_id,
                planned_bucket=bucket,
                tags=list(parsed.tags or []),
                reminder_at=intent.reminder_at,
            )
            if not ok:
                return CaptureExecutionResult(False, "Recurring capture failed. Nesting limit reached for the target parent.")
            new_id = self.model.last_added_task_id()
            if new_id is None:
                return CaptureExecutionResult(False, "Recurring capture failed.")
            self.model.set_task_recurrence(int(new_id), intent.frequency, bool(intent.create_next_on_done))
        finally:
            self.model.undo_stack.endMacro()
        if self.isVisible():
            self._focus_task_by_id(int(new_id))
        message = f"Created recurring {intent.frequency} task."
        if notes or parsed.parse_warnings:
            message = f"{message} {' '.join(notes + list(parsed.parse_warnings))}".strip()
        return CaptureExecutionResult(True, message)

    def _delete_sibling_of_selected(self):
        pidx = self._selected_proxy_index()
        if not pidx:
            return

        src = self.proxy.mapToSource(pidx)
        if not src.isValid():
            return

        parent_src = src.parent()
        row = src.row()

        sibling_src = QModelIndex()

        # Prefer next sibling, else previous sibling
        next_row = row + 1
        if self.model.rowCount(parent_src) > next_row:
            sibling_src = self.model.index(next_row, 0, parent_src)
        elif row - 1 >= 0:
            sibling_src = self.model.index(row - 1, 0, parent_src)

        if not sibling_src.isValid():
            return

        task_id = self.model.task_id_from_index(sibling_src)
        if task_id is None:
            return

        self.model.archive_tasks([task_id])
        self._schedule_row_action_button_update()

    # ---------- Filters ----------
    def _init_filter_dock(self):
        self.filter_panel = FilterPanel(STATUSES, self)
        self.filter_panel.changed.connect(self._apply_filters)

        self.filter_dock = QDockWidget("Filters", self)
        self.filter_dock.setObjectName("FiltersDock")
        self.filter_dock.setWidget(self._wrap_dock_content_scrollable(self.filter_panel, "FiltersDockScroll"))
        self._configure_dock_widget(self.filter_dock)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.filter_dock)
        self.filter_dock.hide()
        self.filter_dock.visibilityChanged.connect(
            lambda vis: self._toggle_filters_act.setChecked(bool(vis)) if hasattr(self, "_toggle_filters_act") else None
        )

    def _configure_dock_widget(self, dock: QDockWidget):
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

    def _init_controls_dock(self):
        self.controls_dock = QDockWidget("Capture and navigation", self)
        self.controls_dock.setObjectName("CaptureNavigationDock")
        self.controls_dock.setWidget(self.controls_scroll)
        self._configure_dock_widget(self.controls_dock)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.controls_dock)
        self.controls_dock.visibilityChanged.connect(
            lambda vis: self._toggle_controls_act.setChecked(bool(vis)) if hasattr(self, "_toggle_controls_act") else None
        )

    def _init_details_dock(self):
        self.details_panel = TaskDetailsPanel(self)

        self.details_dock = QDockWidget("Details", self)
        self.details_dock.setObjectName("DetailsDock")
        self.details_dock.setWidget(self._wrap_dock_content_scrollable(self.details_panel, "DetailsDockScroll"))
        self._configure_dock_widget(self.details_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.details_dock)

        self.details_panel.saveRequested.connect(self._save_details_from_panel)
        self.details_panel.save_btn.clicked.connect(
            self.details_panel.request_immediate_save
        )
        self.details_panel.start_timer_btn.clicked.connect(self._details_start_timer)
        self.details_panel.stop_timer_btn.clicked.connect(self._details_stop_timer)
        self.details_panel.set_reminder_btn.clicked.connect(self._details_set_reminder)
        self.details_panel.set_due_reminder_btn.clicked.connect(self._details_set_due_reminder)
        self.details_panel.clear_reminder_btn.clicked.connect(self._details_clear_reminder)
        self.details_panel.add_file_btn.clicked.connect(self._details_add_file_attachment)
        self.details_panel.add_folder_btn.clicked.connect(self._details_add_folder_attachment)
        self.details_panel.open_attachment_btn.clicked.connect(self._details_open_attachment)
        self.details_panel.remove_attachment_btn.clicked.connect(self._details_remove_attachment)
        self.details_panel.previousParentRequested.connect(lambda: self._navigate_parent_relative(-1))
        self.details_panel.nextParentRequested.connect(lambda: self._navigate_parent_relative(1))
        self.details_panel.previousChildRequested.connect(lambda: self._navigate_child_relative(-1))
        self.details_panel.nextChildRequested.connect(lambda: self._navigate_child_relative(1))
        self.details_panel.parentJumpRequested.connect(self._focus_task_by_id)
        self.details_panel.toggleTableRequested.connect(self._toggle_task_table_visibility)

        self.details_dock.visibilityChanged.connect(
            lambda vis: self._toggle_details_act.setChecked(bool(vis)) if hasattr(self, "_toggle_details_act") else None
        )
        self.details_dock.visibilityChanged.connect(
            lambda vis: self._refresh_details_dock() if vis else None
        )

    def _init_project_dock(self):
        self.project_panel = ProjectCockpitPanel(self)
        self.project_panel.categorySelected.connect(self._project_panel_select_category)
        self.project_panel.addCategoryRequested.connect(self._prompt_new_category)
        self.project_panel.editCategoryRequested.connect(self._customize_category_folder)
        self.project_panel.deleteCategoryRequested.connect(self._delete_category_folder)
        self.project_panel.projectSelected.connect(self._focus_task_by_id)
        self.project_panel.saveProfileRequested.connect(self._project_panel_save_profile)
        self.project_panel.saveBaselineRequested.connect(self._project_panel_save_baseline)
        self.project_panel.addPhaseRequested.connect(self._project_panel_add_phase)
        self.project_panel.renamePhaseRequested.connect(self._project_panel_rename_phase)
        self.project_panel.deletePhaseRequested.connect(self._project_panel_delete_phase)
        self.project_panel.addTaskRequested.connect(self._project_panel_add_task)
        self.project_panel.addMilestoneRequested.connect(self._project_panel_add_milestone)
        self.project_panel.editMilestoneRequested.connect(self._project_panel_edit_milestone)
        self.project_panel.deleteMilestoneRequested.connect(self._project_panel_delete_milestone)
        self.project_panel.addDeliverableRequested.connect(self._project_panel_add_deliverable)
        self.project_panel.editDeliverableRequested.connect(self._project_panel_edit_deliverable)
        self.project_panel.deleteDeliverableRequested.connect(self._project_panel_delete_deliverable)
        self.project_panel.addRegisterEntryRequested.connect(self._project_panel_add_register_entry)
        self.project_panel.editRegisterEntryRequested.connect(self._project_panel_edit_register_entry)
        self.project_panel.deleteRegisterEntryRequested.connect(self._project_panel_delete_register_entry)
        self.project_panel.editTaskDependenciesRequested.connect(
            self._project_panel_edit_task_dependencies
        )
        self.project_panel.editMilestoneDependenciesRequested.connect(
            self._project_panel_edit_milestone_dependencies
        )
        self.project_panel.focusTaskRequested.connect(self._focus_task_by_id)
        self.project_panel.timelineScheduleRequested.connect(
            self._project_panel_schedule_timeline_item
        )
        self.project_panel.timelineTaskMoveRequested.connect(
            self._move_task_to_row_from_timeline
        )
        self.project_panel.timelineTaskMoveRelativeRequested.connect(
            self._move_selected_task_from_timeline
        )

        self.project_dock = QDockWidget("Project cockpit", self)
        self.project_dock.setObjectName("ProjectCockpitDock")
        self.project_dock.setWidget(self._wrap_dock_content_scrollable(self.project_panel, "ProjectCockpitDockScroll"))
        self._configure_dock_widget(self.project_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.project_dock)
        self.project_dock.hide()
        self.project_dock.visibilityChanged.connect(
            lambda vis: self._toggle_project_act.setChecked(bool(vis)) if hasattr(self, "_toggle_project_act") else None
        )
        self.project_dock.visibilityChanged.connect(lambda vis: self._refresh_project_panel() if vis else None)

    def _init_relationships_dock(self):
        self.relationships_panel = RelationshipsPanel(self)
        self.relationships_panel.focusTaskRequested.connect(self._focus_task_by_id)
        self.relationships_panel.closeRequested.connect(lambda: self.relationships_dock.hide())

        self.relationships_dock = QDockWidget("Relationships", self)
        self.relationships_dock.setObjectName("RelationshipsDock")
        self.relationships_dock.setWidget(
            self._wrap_dock_content_scrollable(self.relationships_panel, "RelationshipsDockScroll")
        )
        self._configure_dock_widget(self.relationships_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.relationships_dock)
        self.relationships_dock.hide()
        self.relationships_dock.visibilityChanged.connect(
            lambda vis: self._toggle_relationships_act.setChecked(bool(vis))
            if hasattr(self, "_toggle_relationships_act")
            else None
        )
        self.relationships_dock.visibilityChanged.connect(
            lambda vis: self._refresh_relationships_panel() if vis else None
        )

    def _init_undo_history_dock(self):
        self.undo_view = QUndoView(self.undo_stack, self)
        self.undo_view.setObjectName("UndoHistoryView")
        self.undo_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.undo_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        undo_panel = SectionPanel(
            "Undo history",
            "Recent undo commands stay visible in order, so it is clear what "
            "state changes are available to walk back.",
        )
        undo_panel.body_layout.addWidget(self.undo_view, 1)
        self.undo_dock = QDockWidget("Undo History", self)
        self.undo_dock.setObjectName("UndoHistoryDock")
        self.undo_dock.setWidget(self._wrap_dock_content_scrollable(undo_panel, "UndoHistoryDockScroll"))
        self._configure_dock_widget(self.undo_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.undo_dock)
        self.undo_dock.hide()
        self.undo_dock.visibilityChanged.connect(
            lambda vis: self._toggle_undo_history_act.setChecked(bool(vis))
            if hasattr(self, "_toggle_undo_history_act")
            else None
        )

    def _init_focus_dock(self):
        self.focus_panel = FocusPanel(self)
        self.focus_panel.refreshRequested.connect(self._refresh_focus_panel)
        self.focus_panel.focusTaskRequested.connect(self._focus_panel_focus_task)
        self.focus_panel.openDetailsRequested.connect(self._focus_panel_open_details)
        self.focus_panel.closeRequested.connect(lambda: self.focus_dock.hide())

        self.focus_dock = QDockWidget("Focus Mode", self)
        self.focus_dock.setObjectName("FocusDock")
        self.focus_dock.setWidget(self._wrap_dock_content_scrollable(self.focus_panel, "FocusDockScroll"))
        self._configure_dock_widget(self.focus_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.focus_dock)
        self.focus_dock.hide()
        self.focus_dock.visibilityChanged.connect(
            lambda vis: self._toggle_focus_act.setChecked(bool(vis)) if hasattr(self, "_toggle_focus_act") else None
        )
        self.focus_dock.visibilityChanged.connect(lambda vis: self._refresh_focus_panel() if vis else None)

    def _init_review_dock(self):
        self.review_panel = ReviewWorkflowPanel(self)
        self.review_panel.refreshRequested.connect(self._refresh_review_panel)
        self.review_panel.focusTaskRequested.connect(self._review_focus_task)
        self.review_panel.markDoneRequested.connect(self._review_mark_done)
        self.review_panel.archiveRequested.connect(self._review_archive)
        self.review_panel.restoreRequested.connect(self._review_restore)
        self.review_panel.acknowledgeRequested.connect(self._review_acknowledge)
        self.review_panel.clearAcknowledgedRequested.connect(self._review_clear_acknowledged)
        self.review_panel.useCategoryRequested.connect(self._review_use_category)

        self.review_dock = QDockWidget("Review Workflow", self)
        self.review_dock.setObjectName("ReviewDock")
        self.review_dock.setWidget(self._wrap_dock_content_scrollable(self.review_panel, "ReviewDockScroll"))
        self._configure_dock_widget(self.review_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.review_dock)
        self.review_dock.hide()
        self.review_dock.visibilityChanged.connect(
            lambda vis: self._toggle_review_act.setChecked(bool(vis)) if hasattr(self, "_toggle_review_act") else None
        )
        self.review_dock.visibilityChanged.connect(lambda vis: self._refresh_review_panel() if vis else None)

    def _init_analytics_dock(self):
        self.analytics_panel = AnalyticsPanel(self)
        self.analytics_panel.refreshRequested.connect(self._refresh_analytics_panel)

        self.analytics_dock = QDockWidget("Analytics", self)
        self.analytics_dock.setObjectName("AnalyticsDock")
        self.analytics_dock.setWidget(self._wrap_dock_content_scrollable(self.analytics_panel, "AnalyticsDockScroll"))
        self._configure_dock_widget(self.analytics_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.analytics_dock)
        self.analytics_dock.hide()
        self.analytics_dock.visibilityChanged.connect(
            lambda vis: self._toggle_analytics_act.setChecked(bool(vis)) if hasattr(self, "_toggle_analytics_act") else None
        )
        self.analytics_dock.visibilityChanged.connect(lambda vis: self._refresh_analytics_panel() if vis else None)

    def _init_calendar_dock(self):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        configure_box_layout(v, margins=(6, 6, 6, 6), spacing=8)

        calendar_section = SectionPanel(
            "Calendar",
            "Browse dated work at a glance and create a task directly from a "
            "day by double-clicking it.",
        )
        self.calendar_help_btn = attach_context_help(
            calendar_section,
            "calendar_agenda",
            self,
            tooltip="Open help for the calendar and agenda view",
        )
        self.calendar = TaskCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(self.calendar.VerticalHeaderFormat.ISOWeekNumbers)
        self.calendar.selectionChanged.connect(self._refresh_calendar_list)
        self.calendar.activated.connect(self._on_calendar_date_activated)
        self.calendar.currentPageChanged.connect(lambda *_: self._refresh_calendar_markers())
        calendar_section.body_layout.addWidget(self.calendar)
        v.addWidget(calendar_section)

        agenda_section = SectionPanel(
            "Agenda",
            "Tasks for the selected date stay grouped below the calendar "
            "instead of floating in a separate generic box.",
        )
        self.calendar_list = QListWidget()
        self.calendar_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.calendar_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.calendar_list.itemActivated.connect(self._on_calendar_task_activated)
        self.calendar_list.itemDoubleClicked.connect(self._on_calendar_task_activated)
        self.calendar_list_stack = EmptyStateStack(
            self.calendar_list,
            "No tasks on the selected date.",
            "Select a different day or double-click the calendar to add one.",
        )
        agenda_section.body_layout.addWidget(self.calendar_list_stack, 1)
        v.addWidget(agenda_section, 1)

        self.calendar_dock = QDockWidget("Calendar / Agenda", self)
        self.calendar_dock.setObjectName("CalendarDock")
        self.calendar_dock.setWidget(self._wrap_dock_content_scrollable(wrap, "CalendarDockScroll"))
        self._configure_dock_widget(self.calendar_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.calendar_dock)
        self.calendar_dock.hide()
        self.calendar_dock.visibilityChanged.connect(
            lambda vis: self._toggle_calendar_act.setChecked(bool(vis)) if hasattr(self, "_toggle_calendar_act") else None
        )

    def _wrap_dock_content_scrollable(self, content: QWidget, object_name: str) -> QScrollArea:
        layout = content.layout()
        if layout is not None:
            layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        try:
            min_width = max(content.minimumSizeHint().width(), content.sizeHint().width())
        except Exception:
            min_width = content.minimumWidth()
        if int(min_width or 0) > 0:
            content.setMinimumWidth(int(min_width))
        content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _task_id_for_proxy_index(self, pidx: QModelIndex) -> int | None:
        if not pidx.isValid():
            return None
        src = self.proxy.mapToSource(pidx)
        tid = self.model.task_id_from_index(src)
        return int(tid) if tid is not None else None

    def _top_level_proxy_indexes(self) -> list[QModelIndex]:
        rows: list[QModelIndex] = []
        root = QModelIndex()
        for row in range(self.proxy.rowCount(root)):
            idx = self.proxy.index(row, 0, root)
            if idx.isValid():
                rows.append(idx)
        return rows

    def _iter_proxy_subtree_indexes(self, parent: QModelIndex) -> list[QModelIndex]:
        rows: list[QModelIndex] = []
        if not parent.isValid():
            return rows
        rows.append(parent)
        for row in range(self.proxy.rowCount(parent)):
            child = self.proxy.index(row, 0, parent)
            if not child.isValid():
                continue
            rows.extend(self._iter_proxy_subtree_indexes(child))
        return rows

    def _top_level_task_id_for_task(self, task_id: int | None) -> int | None:
        if task_id is None:
            return None
        node = self.model.node_for_id(int(task_id))
        if not node or not node.task:
            return None
        while node.parent is not None and node.parent.task is not None:
            node = node.parent
        try:
            return int(node.task["id"]) if node.task else None
        except Exception:
            return None

    def _expand_proxy_ancestors(self, pidx: QModelIndex):
        chain: list[QModelIndex] = []
        probe = pidx.parent()
        while probe.isValid():
            chain.append(probe)
            probe = probe.parent()
        for ancestor in reversed(chain):
            self.view.expand(ancestor)

    def _collect_task_browser_state(self) -> dict:
        parents: list[tuple[int, str]] = []
        parent_ids: list[int] = []
        for idx in self._top_level_proxy_indexes():
            tid = self._task_id_for_proxy_index(idx)
            if tid is None:
                continue
            label = str(self.proxy.data(idx, Qt.ItemDataRole.DisplayRole) or "").strip() or f"Task {tid}"
            parents.append((int(tid), label))
            parent_ids.append(int(tid))

        current_task_id = self._selected_task_id()
        current_parent_id = self._top_level_task_id_for_task(current_task_id)
        if current_parent_id is None and parent_ids:
            current_parent_id = int(parent_ids[0])

        current_parent_position = 0
        current_parent_total = len(parent_ids)
        subtree_ids: list[int] = []
        current_item_position = 0
        current_item_total = 0

        if current_parent_id is not None and current_parent_id in parent_ids:
            current_parent_position = parent_ids.index(int(current_parent_id)) + 1
            src = self._source_index_for_task_id(int(current_parent_id), 0)
            if src.isValid():
                root_proxy = self.proxy.mapFromSource(src)
                if root_proxy.isValid():
                    subtree_ids = [
                        tid
                        for tid in (self._task_id_for_proxy_index(idx) for idx in self._iter_proxy_subtree_indexes(root_proxy))
                        if tid is not None
                    ]
                    current_item_total = len(subtree_ids)
                    if current_task_id is not None and int(current_task_id) in subtree_ids:
                        current_item_position = subtree_ids.index(int(current_task_id)) + 1

        return {
            "parents": parents,
            "parent_ids": parent_ids,
            "current_parent_id": current_parent_id,
            "current_parent_position": current_parent_position,
            "current_parent_total": current_parent_total,
            "subtree_ids": subtree_ids,
            "current_item_position": current_item_position,
            "current_item_total": current_item_total,
            "tree_visible": self._is_task_table_visible(),
        }

    def _refresh_task_browser(self):
        if not hasattr(self, "details_panel"):
            return
        state = self._collect_task_browser_state()
        self.details_panel.set_navigation_state(
            parents=list(state.get("parents") or []),
            current_parent_id=state.get("current_parent_id"),
            current_parent_position=int(state.get("current_parent_position") or 0),
            current_parent_total=int(state.get("current_parent_total") or 0),
            current_item_position=int(state.get("current_item_position") or 0),
            current_item_total=int(state.get("current_item_total") or 0),
            can_prev_parent=int(state.get("current_parent_position") or 0) > 1,
            can_next_parent=0 < int(state.get("current_parent_position") or 0) < int(state.get("current_parent_total") or 0),
            can_prev_child=int(state.get("current_item_position") or 0) > 1,
            can_next_child=0 < int(state.get("current_item_position") or 0) < int(state.get("current_item_total") or 0),
            tree_visible=bool(state.get("tree_visible")),
        )

    def _is_task_table_floating(self) -> bool:
        return bool(self._floating_table_window is not None and self._floating_table_window.centralWidget() is self.tree_wrap)

    def _is_task_table_visible(self) -> bool:
        if self._is_task_table_floating():
            return bool(self._floating_table_window is not None and self._floating_table_window.isVisible())
        return bool(getattr(self, "tree_wrap", None) and not self.tree_wrap.isHidden())

    def _ensure_floating_table_window(self) -> FloatingTaskTableWindow:
        if self._floating_table_window is None:
            win = FloatingTaskTableWindow(self)
            win.setWindowTitle(f"{APP_NAME} - Task table")
            icon = self.windowIcon()
            if icon is not None:
                win.setWindowIcon(icon)
            win.dockRequested.connect(lambda: self._set_task_table_floating(False))
            self._floating_table_window = win
        return self._floating_table_window

    def _update_task_table_placeholder(self):
        if not hasattr(self, "_table_placeholder"):
            return
        self._table_placeholder.hide()
        central = self.centralWidget()
        if central is not None:
            central.setVisible(
                not self._is_task_table_floating() and self._is_task_table_visible()
            )

    def _set_task_table_floating(self, floating: bool, *, show_after: bool | None = None):
        want_floating = bool(floating)
        currently_floating = self._is_task_table_floating()
        if want_floating == currently_floating:
            if show_after is not None:
                self._set_tree_visible(bool(show_after), show_message=False)
            return

        if want_floating:
            win = self._ensure_floating_table_window()
            self.tree_wrap.setParent(None)
            win.setCentralWidget(self.tree_wrap)
            if show_after is None:
                show_after = True
            if show_after:
                win.show()
                win.raise_()
                win.activateWindow()
            else:
                win.hide()
        else:
            visible_before = self._is_task_table_visible()
            win = self._ensure_floating_table_window()
            widget = win.takeCentralWidget()
            if widget is not None and widget is self.tree_wrap:
                self._table_host_layout.addWidget(self.tree_wrap, 1)
            win.hide()
            if show_after is None:
                show_after = visible_before
            self.tree_wrap.setHidden(not bool(show_after))

        if hasattr(self, "_float_table_act"):
            blocked = self._float_table_act.blockSignals(True)
            self._float_table_act.setChecked(want_floating)
            self._float_table_act.blockSignals(blocked)
        if show_after is not None and not want_floating:
            self.tree_wrap.setHidden(not bool(show_after))
        self.row_add_btn.hide()
        self.row_del_btn.hide()
        self._update_task_table_placeholder()
        self.model.settings.setValue("ui/tree_floating", want_floating)
        self._refresh_task_browser()
        if not want_floating and bool(show_after):
            self._schedule_task_header_layout()
        self._schedule_row_action_button_update()

    def _show_controls_dock(self):
        if hasattr(self, "controls_dock"):
            self.controls_dock.show()
            if hasattr(self, "_toggle_controls_act"):
                self._toggle_controls_act.setChecked(True)

    def _show_and_focus_dock(
        self,
        dock: QDockWidget | None,
        focus_target,
        *,
        refresh=None,
    ):
        if dock is None:
            return
        dock.show()
        if callable(refresh):
            refresh()
        if dock.isFloating():
            dock.raise_()
            dock.activateWindow()

        def _apply_focus():
            target = focus_target() if callable(focus_target) else focus_target
            if target is not None:
                try:
                    target.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    return
                except Exception:
                    pass
            try:
                dock.setFocus(Qt.FocusReason.ShortcutFocusReason)
            except Exception:
                pass

        QTimer.singleShot(0, _apply_focus)

    def _focus_search_input(self):
        self._show_controls_dock()
        self.search.setFocus()
        self.search.selectAll()

    def _focus_quick_add_input(self):
        self._show_controls_dock()
        self.quick_add.setFocus()
        self.quick_add.selectAll()

    def _focus_task_workspace(self):
        if not self._is_task_table_visible():
            self._set_tree_visible(True, show_message=False)
        if self._is_task_table_floating():
            win = self._ensure_floating_table_window()
            win.show()
            win.raise_()
            win.activateWindow()

        def _apply_focus():
            try:
                self.view.setFocus(Qt.FocusReason.ShortcutFocusReason)
                idx = self.view.currentIndex()
                if idx.isValid():
                    self.view.scrollTo(idx)
            except Exception:
                pass

        QTimer.singleShot(0, _apply_focus)

    def _focus_details_panel(self):
        self._show_and_focus_dock(
            getattr(self, "details_dock", None),
            lambda: getattr(self.details_panel, "notes", None),
        )

    def _focus_filters_panel(self):
        self._show_and_focus_dock(
            getattr(self, "filter_dock", None),
            lambda: getattr(self.filter_panel, "tags_input", None),
        )

    def _focus_project_panel(self):
        self._show_and_focus_dock(
            getattr(self, "project_dock", None),
            lambda: self.project_panel.focus_target(),
            refresh=self._refresh_project_panel,
        )

    def _focus_relationships_panel(self):
        self._show_and_focus_dock(
            getattr(self, "relationships_dock", None),
            lambda: self.relationships_panel.focus_target(),
            refresh=self._refresh_relationships_panel,
        )

    def _focus_focus_panel(self):
        self._show_and_focus_dock(
            getattr(self, "focus_dock", None),
            lambda: getattr(self.focus_panel, "list", None),
            refresh=self._refresh_focus_panel,
        )

    def _focus_review_panel(self):
        self._show_and_focus_dock(
            getattr(self, "review_dock", None),
            lambda: self.review_panel.focus_target(),
            refresh=self._refresh_review_panel,
        )

    def _focus_calendar_panel(self):
        self._show_and_focus_dock(
            getattr(self, "calendar_dock", None),
            lambda: getattr(self, "calendar", None),
            refresh=self._refresh_calendar_list,
        )

    def _focus_analytics_panel(self):
        self._show_and_focus_dock(
            getattr(self, "analytics_dock", None),
            lambda: getattr(self.analytics_panel, "trend_list", None),
            refresh=self._refresh_analytics_panel,
        )

    def _focus_undo_history_panel(self):
        self._show_and_focus_dock(
            getattr(self, "undo_dock", None),
            lambda: getattr(self, "undo_view", None),
        )

    def _navigate_parent_relative(self, delta: int):
        state = self._collect_task_browser_state()
        parent_ids = [int(tid) for tid in (state.get("parent_ids") or [])]
        if not parent_ids:
            return
        current_parent_id = state.get("current_parent_id")
        try:
            index = parent_ids.index(int(current_parent_id))
        except Exception:
            index = 0 if int(delta) >= 0 else len(parent_ids) - 1
        new_index = index + int(delta)
        if 0 <= new_index < len(parent_ids):
            self._focus_task_by_id(int(parent_ids[new_index]))

    def _navigate_child_relative(self, delta: int):
        state = self._collect_task_browser_state()
        subtree_ids = [int(tid) for tid in (state.get("subtree_ids") or [])]
        if not subtree_ids:
            return
        current_task_id = self._selected_task_id()
        if current_task_id is None or int(current_task_id) not in subtree_ids:
            target_index = 0 if int(delta) >= 0 else len(subtree_ids) - 1
            self._focus_task_by_id(int(subtree_ids[target_index]))
            return
        current_index = subtree_ids.index(int(current_task_id))
        new_index = current_index + int(delta)
        if 0 <= new_index < len(subtree_ids):
            self._focus_task_by_id(int(subtree_ids[new_index]))

    def _set_tree_visible(self, visible: bool, *, show_message: bool = True):
        if not hasattr(self, "tree_wrap"):
            return
        show_tree = bool(visible)
        if self._is_task_table_floating():
            win = self._ensure_floating_table_window()
            if show_tree:
                win.show()
                win.raise_()
                win.activateWindow()
            else:
                win.hide()
        else:
            self.tree_wrap.setHidden(not show_tree)
        self.row_add_btn.hide()
        self.row_del_btn.hide()
        if hasattr(self, "_toggle_table_act"):
            blocked = self._toggle_table_act.blockSignals(True)
            self._toggle_table_act.setChecked(show_tree)
            self._toggle_table_act.blockSignals(blocked)
        if not show_tree and hasattr(self, "details_dock") and not self.details_dock.isVisible():
            self.details_dock.show()
            if hasattr(self, "_toggle_details_act"):
                self._toggle_details_act.setChecked(True)
        if show_message:
            if show_tree:
                self.statusBar().showMessage("Task table shown.", 2500)
            else:
                self.statusBar().showMessage(
                    "Task table hidden. Use the Details browser or other docks to keep navigating tasks.",
                    4000,
                )
        self.model.settings.setValue("ui/tree_visible", show_tree)
        self._refresh_task_browser()
        self._update_task_table_placeholder()
        if show_tree:
            self._schedule_task_header_layout()
        self._schedule_row_action_button_update()

    def _toggle_task_table_visibility(self):
        visible = self._is_task_table_visible()
        self._set_tree_visible(not visible)

    def _db_available(self) -> bool:
        if bool(getattr(self, "_closing_down", False)):
            return False
        db = getattr(self, "db", None)
        return bool(db is not None and getattr(db, "conn", None) is not None)

    def _selected_task_details(self) -> dict | None:
        if not self._db_available():
            return None
        tid = self._selected_task_id()
        if tid is None:
            return None
        return self.model.task_details(int(tid))

    def _active_task_status_text(self, details: dict | None) -> str:
        if not details:
            return "Active task: none"
        desc = str(details.get("description") or "").strip() or "(untitled task)"
        status = str(details.get("status") or "").strip() or "Unknown"
        priority = str(details.get("priority") or "").strip() or "-"
        return f"Active task: [P{priority}] {desc} | {status}"

    def _update_active_task_status_label(self, details: dict | None):
        if not hasattr(self, "_active_task_label"):
            return
        text = self._active_task_status_text(details)
        self._active_task_label.setText(text)
        self._active_task_label.setToolTip(text)
        self._active_task_label.setStatusTip(text)

    def _clear_task_browser(self):
        if not hasattr(self, "details_panel"):
            return
        self.details_panel.set_navigation_state(
            parents=[],
            current_parent_id=None,
            current_parent_position=0,
            current_parent_total=0,
            current_item_position=0,
            current_item_total=0,
            can_prev_parent=False,
            can_next_parent=False,
            can_prev_child=False,
            can_next_child=False,
            tree_visible=bool(self._is_task_table_visible()),
        )

    def _clear_active_task_views(self):
        self._active_task_details = None
        self._active_task_id = None
        self._project_panel_context_signature = None
        self._project_panel_dirty = True
        self._update_active_task_status_label(None)
        if hasattr(self, "details_panel"):
            self.details_panel.set_task_details(None)
        if hasattr(self, "project_panel"):
            self.project_panel.set_category_choices([], None)
            self.project_panel.set_project_choices([], None)
            self.project_panel.set_dashboard(None)
        if hasattr(self, "relationships_panel"):
            self.relationships_panel.set_relationships(None)
        if hasattr(self, "focus_panel"):
            self.focus_panel.set_current_summary("Current selection: none", None)
        self._clear_task_browser()

    def _schedule_active_task_view_refresh(self):
        if self._active_task_views_refresh_pending:
            return
        self._active_task_views_refresh_pending = True
        QTimer.singleShot(0, self._flush_active_task_view_refresh)

    def _flush_active_task_view_refresh(self):
        self._active_task_views_refresh_pending = False
        self._refresh_active_task_views()

    def _schedule_focus_panel_refresh(self):
        if self._focus_panel_refresh_pending:
            return
        self._focus_panel_refresh_pending = True
        QTimer.singleShot(0, self._flush_focus_panel_refresh)

    def _flush_focus_panel_refresh(self):
        self._focus_panel_refresh_pending = False
        self._refresh_focus_panel()

    def _schedule_review_panel_refresh(self):
        if self._review_panel_refresh_pending:
            return
        self._review_panel_refresh_pending = True
        QTimer.singleShot(0, self._flush_review_panel_refresh)

    def _flush_review_panel_refresh(self):
        self._review_panel_refresh_pending = False
        self._refresh_review_panel()

    def _schedule_analytics_panel_refresh(self):
        if self._analytics_panel_refresh_pending:
            return
        self._analytics_panel_refresh_pending = True
        QTimer.singleShot(0, self._flush_analytics_panel_refresh)

    def _flush_analytics_panel_refresh(self):
        self._analytics_panel_refresh_pending = False
        self._refresh_analytics_panel()

    def _schedule_calendar_marker_refresh(self):
        if self._calendar_marker_refresh_pending:
            return
        self._calendar_marker_refresh_pending = True
        QTimer.singleShot(0, self._flush_calendar_marker_refresh)

    def _flush_calendar_marker_refresh(self):
        self._calendar_marker_refresh_pending = False
        self._refresh_calendar_markers()

    def _mark_project_panel_dirty(self, *_):
        self._project_panel_dirty = True

    def _restore_task_focus_if_needed(self, task_id: int | None):
        if task_id is None or not self._db_available():
            return
        current_task_id = self._selected_task_id()
        if current_task_id == int(task_id):
            return
        self._focus_task_by_id(int(task_id))

    def _refresh_relationships_panel_from_details(self, details: dict | None):
        with measure_ui(
            "main._refresh_relationships_panel",
            visible=bool(
                hasattr(self, "relationships_dock")
                and self.relationships_dock.isVisible()
            ),
        ):
            if not hasattr(self, "relationships_panel"):
                return
            if hasattr(self, "relationships_dock") and not self.relationships_dock.isVisible():
                return
            if not self._db_available():
                self.relationships_panel.set_relationships(None)
                return
            if not details or details.get("id") is None:
                self.relationships_panel.set_relationships(None)
                return
            data = self.model.task_relationships(int(details["id"]), limit=10)
            self.relationships_panel.set_relationships(data)

    def _selected_category_folder_id(self, details: dict | None = None) -> int | None:
        idx = self._selected_proxy_index()
        if idx is not None:
            src = self.proxy.mapToSource(idx)
            folder_id = self.model.folder_id_from_index(src)
            if folder_id is not None:
                return int(folder_id)
        if details and details.get("category_folder_id") is not None:
            return int(details["category_folder_id"])
        return None

    def _refresh_project_panel_from_details(
        self,
        details: dict | None,
        category_folder_id=_UNSET,
        *,
        force: bool = False,
    ):
        with measure_ui(
            "main._refresh_project_panel",
            visible=bool(
                hasattr(self, "project_dock")
                and self.project_dock.isVisible()
            ),
        ):
            if not hasattr(self, "project_panel"):
                return
            if hasattr(self, "project_dock") and not self.project_dock.isVisible():
                return
            if not self._db_available():
                self.project_panel.set_category_choices([], None)
                self.project_panel.set_project_choices([], None)
                self.project_panel.set_dashboard(None)
                self._project_panel_context_signature = None
                self._project_panel_dirty = True
                return
            current_folder_id = (
                self._selected_category_folder_id(details)
                if category_folder_id is _UNSET
                else (
                    None if category_folder_id is None else int(category_folder_id)
                )
            )
            current_project_id = (
                int(details["project_id"])
                if details and details.get("project_id") is not None
                else None
            )
            context_signature = (current_folder_id, current_project_id)
            active_task_id = (
                int(details["id"])
                if details and details.get("id") is not None
                else None
            )
            if (
                not force
                and context_signature == self._project_panel_context_signature
                and not self._project_panel_dirty
            ):
                self.project_panel.set_active_task(active_task_id)
                return
            self.project_panel.set_category_choices(
                self.model.list_category_folders(),
                current_folder_id,
            )
            projects = self.model.list_project_candidates(folder_id=current_folder_id)
            visible_ids = {int(row.get("id") or 0) for row in projects}
            existing_project_id = self.project_panel.project_combo.currentData()
            if current_project_id is None and existing_project_id is not None:
                existing_project_id = int(existing_project_id)
                current_project_id = existing_project_id if existing_project_id in visible_ids else None
            self.project_panel.set_project_choices(
                projects,
                current_project_id,
            )
            if (
                current_project_id is None
                and self.project_panel.project_combo.currentData() is not None
            ):
                current_project_id = int(self.project_panel.project_combo.currentData())
                context_signature = (current_folder_id, current_project_id)
            if current_project_id is None:
                self.project_panel.set_dashboard(None)
                self.project_panel.set_active_task(active_task_id)
                self._project_panel_context_signature = context_signature
                self._project_panel_dirty = False
                return
            try:
                dashboard = self.model.fetch_project_dashboard(int(current_project_id))
            except Exception as e:
                QMessageBox.warning(self, "Project cockpit refresh failed", str(e))
                return
            self.project_panel.set_dashboard(dashboard)
            self.project_panel.set_active_task(active_task_id)
            self._project_panel_context_signature = context_signature
            self._project_panel_dirty = False

    def _refresh_active_task_views(self):
        visible = any(
            (
                hasattr(self, "details_dock") and self.details_dock.isVisible(),
                hasattr(self, "project_dock") and self.project_dock.isVisible(),
                hasattr(self, "relationships_dock")
                and self.relationships_dock.isVisible(),
                hasattr(self, "focus_dock") and self.focus_dock.isVisible(),
            )
        )
        with measure_ui("main._refresh_active_task_views", visible=visible):
            if not self._db_available():
                self._clear_active_task_views()
                return
            details = self._selected_task_details()
            self._active_task_details = details
            self._active_task_id = (
                int(details["id"])
                if details and details.get("id") is not None
                else None
            )
            self._update_active_task_status_label(details)
            if (
                hasattr(self, "details_panel")
                and hasattr(self, "details_dock")
                and self.details_dock.isVisible()
            ):
                self.details_panel.set_task_details(details)
            self._refresh_project_panel_from_details(details)
            self._refresh_relationships_panel_from_details(details)
            if (
                hasattr(self, "focus_panel")
                and hasattr(self, "focus_dock")
                and self.focus_dock.isVisible()
            ):
                self.focus_panel.set_current_summary(
                    self._focus_current_summary(details),
                    self._active_task_id,
                )
            if hasattr(self, "details_dock") and self.details_dock.isVisible():
                self._refresh_task_browser()

    def _refresh_details_dock(self):
        self._refresh_active_task_views()

    def _refresh_relationships_panel(self):
        self._refresh_relationships_panel_from_details(self._selected_task_details())

    def _current_project_id(self) -> int | None:
        tid = self._selected_task_id()
        if tid is None:
            return None
        return self.model.project_id_for_task(int(tid))

    def _refresh_project_panel(self):
        self._refresh_project_panel_from_details(
            self._selected_task_details(),
            force=True,
        )

    def _project_panel_select_category(self, folder_id: int | None):
        self._refresh_project_panel_from_details(
            self._selected_task_details(),
            category_folder_id=folder_id,
            force=True,
        )

    def _project_panel_save_profile(self, project_task_id: int, payload: dict):
        preserved_task_id = self._selected_task_id()
        try:
            self.model.save_project_profile(int(project_task_id), payload)
        except Exception as e:
            QMessageBox.warning(self, "Project save failed", str(e))
            return
        self.project_panel.mark_profile_saved(payload)
        self._refresh_project_panel()
        self._restore_task_focus_if_needed(preserved_task_id)

    def _project_panel_save_baseline(self, project_task_id: int, target_date: str | None, effort_minutes: int | None):
        preserved_task_id = self._selected_task_id()
        try:
            self.model.save_project_baseline(int(project_task_id), target_date, effort_minutes)
        except Exception as e:
            QMessageBox.warning(self, "Baseline save failed", str(e))
            return
        self.project_panel.mark_baseline_saved(target_date, effort_minutes)
        self._refresh_project_panel()
        self._restore_task_focus_if_needed(preserved_task_id)

    def _project_panel_add_phase(self, project_task_id: int, name: str):
        try:
            self.model.add_project_phase(int(project_task_id), str(name))
        except Exception as e:
            QMessageBox.warning(self, "Add phase failed", str(e))
            return
        self._refresh_project_panel()
        self._refresh_details_dock()

    def _project_panel_add_task(self, payload: dict):
        data = dict(payload or {})
        description = str(data.get("description") or "New task").strip() or "New task"
        parent_id = data.get("parent_id")
        phase_id = data.get("phase_id")
        start_date = str(data.get("start_date") or "").strip() or None
        due_date = str(data.get("due_date") or "").strip() or start_date
        bucket = "today"
        if due_date and due_date > date.today().isoformat():
            bucket = "upcoming"

        self.model.undo_stack.beginMacro("Add task from planner")
        try:
            ok = self.model.add_task_with_values(
                description=description,
                due_date=due_date,
                priority=None,
                parent_id=None if parent_id is None else int(parent_id),
                planned_bucket=bucket,
            )
            if not ok:
                self.statusBar().showMessage(
                    "Planner task creation failed. Nesting limit reached for the target parent.",
                    4000,
                )
                return
            new_id = self.model.last_added_task_id()
            if new_id is None:
                return
            if start_date:
                self.model.set_task_start_date(int(new_id), start_date)
            if phase_id is not None:
                self.model.set_task_phase(int(new_id), int(phase_id))
        finally:
            self.model.undo_stack.endMacro()

        log_event(
            "Planner task created",
            context="project.timeline.create",
            db_path=self.db.path,
            details={
                "task_id": int(new_id),
                "parent_id": None if parent_id is None else int(parent_id),
                "phase_id": None if phase_id is None else int(phase_id),
                "start_date": start_date,
                "due_date": due_date,
            },
        )
        self._focus_task_by_id(int(new_id))
        self.statusBar().showMessage(
            "Task added from timeline. Drag or resize the bar to refine its schedule.",
            4000,
        )

    def _project_panel_rename_phase(self, phase_id: int, name: str):
        try:
            self.model.update_project_phase(int(phase_id), str(name))
        except Exception as e:
            QMessageBox.warning(self, "Rename phase failed", str(e))
            return
        self._refresh_project_panel()
        self._refresh_details_dock()

    def _project_panel_delete_phase(self, phase_id: int):
        try:
            self.model.delete_project_phase(int(phase_id))
        except Exception as e:
            QMessageBox.warning(self, "Remove phase failed", str(e))
            return
        self._refresh_project_panel()
        self._refresh_details_dock()

    def _project_panel_add_milestone(self, payload: dict):
        try:
            self.model.upsert_milestone(dict(payload))
        except Exception as e:
            QMessageBox.warning(self, "Milestone save failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_edit_milestone(self, milestone_id: int, payload: dict):
        data = dict(payload)
        data["id"] = int(milestone_id)
        try:
            self.model.upsert_milestone(data)
        except Exception as e:
            QMessageBox.warning(self, "Milestone update failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_delete_milestone(self, milestone_id: int):
        try:
            self.model.delete_milestone(int(milestone_id))
        except Exception as e:
            QMessageBox.warning(self, "Milestone delete failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_add_deliverable(self, payload: dict):
        try:
            self.model.upsert_deliverable(dict(payload))
        except Exception as e:
            QMessageBox.warning(self, "Deliverable save failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_edit_deliverable(self, deliverable_id: int, payload: dict):
        data = dict(payload)
        data["id"] = int(deliverable_id)
        try:
            self.model.upsert_deliverable(data)
        except Exception as e:
            QMessageBox.warning(self, "Deliverable update failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_delete_deliverable(self, deliverable_id: int):
        try:
            self.model.delete_deliverable(int(deliverable_id))
        except Exception as e:
            QMessageBox.warning(self, "Deliverable delete failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_add_register_entry(self, payload: dict):
        try:
            self.model.upsert_project_register_entry(dict(payload))
        except Exception as e:
            QMessageBox.warning(self, "Register entry save failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_edit_register_entry(self, entry_id: int, payload: dict):
        data = dict(payload)
        data["id"] = int(entry_id)
        try:
            self.model.upsert_project_register_entry(data)
        except Exception as e:
            QMessageBox.warning(self, "Register entry update failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_delete_register_entry(self, entry_id: int):
        try:
            self.model.delete_project_register_entry(int(entry_id))
        except Exception as e:
            QMessageBox.warning(self, "Register entry delete failed", str(e))
            return
        self._refresh_project_panel()

    def _save_details_from_panel(
        self,
        task_id: int | None = None,
        payload: dict | None = None,
    ):
        tid = (
            int(task_id)
            if task_id is not None
            else self.details_panel.task_id()
        )
        if tid is None:
            return
        detail_payload = dict(payload or self.details_panel.collect_payload())
        preserved_task_id = self._selected_task_id()
        self.model.undo_stack.beginMacro("Update task details")
        try:
            self.model.set_task_notes(int(tid), detail_payload["notes"])
            self.model.set_task_tags(int(tid), detail_payload["tags"])
            self.model.set_task_bucket(int(tid), detail_payload["bucket"])
            self.model.set_task_start_date(int(tid), detail_payload.get("start_date"))
            self.model.set_task_phase(int(tid), detail_payload.get("phase_id"))
            self.model.set_task_waiting_for(int(tid), detail_payload["waiting_for"])
            self.model.set_task_dependencies(int(tid), detail_payload["dependencies"])
            self.model.set_task_recurrence(
                int(tid),
                detail_payload["recurrence"],
                bool(detail_payload["recurrence_next_on_done"]),
            )
            self.model.set_task_effort_minutes(
                int(tid),
                detail_payload["effort_minutes"],
            )
            self.model.set_task_actual_minutes(
                int(tid),
                detail_payload["actual_minutes"],
            )
        finally:
            self.model.undo_stack.endMacro()
        self.details_panel.mark_saved(int(tid), detail_payload)
        self._refresh_details_dock()
        self._refresh_calendar_list()
        self._restore_task_focus_if_needed(preserved_task_id)

    def _details_start_timer(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        self.model.start_task_timer(int(tid))
        self._refresh_details_dock()

    def _details_stop_timer(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        self.model.stop_task_timer(int(tid))
        self._refresh_details_dock()

    def _details_set_reminder(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        self.model.set_task_reminder(
            int(tid),
            self.details_panel.reminder_iso(),
            int(self.details_panel.reminder_before_minutes.value()),
        )
        self._refresh_details_dock()

    def _details_set_due_reminder(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        details = self.model.task_details(int(tid)) or {}
        due = str(details.get("due_date") or "").strip()
        if not due:
            QMessageBox.information(self, "No due date", "This task has no due date set.")
            return
        try:
            due_dt = datetime.strptime(due[:10], "%Y-%m-%d")
        except Exception:
            QMessageBox.warning(self, "Invalid due date", "The task due date format is invalid.")
            return
        mins = int(self.details_panel.reminder_before_minutes.value())
        rem_dt = due_dt - timedelta(minutes=mins)
        self.model.set_task_reminder(int(tid), rem_dt.strftime("%Y-%m-%d %H:%M:%S"), mins)
        self._refresh_details_dock()

    def _details_clear_reminder(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        self.model.clear_task_reminder(int(tid))
        self._refresh_details_dock()

    def _details_add_file_attachment(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to attach")
        if not paths:
            return
        self.model.undo_stack.beginMacro("Attach files")
        try:
            for p in paths:
                try:
                    self.model.add_attachment(int(tid), p, "")
                except Exception:
                    continue
        finally:
            self.model.undo_stack.endMacro()
        self._refresh_details_dock()

    def _details_add_folder_attachment(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        path = QFileDialog.getExistingDirectory(self, "Select folder to attach")
        if not path:
            return
        try:
            self.model.add_attachment(int(tid), path, "")
        except Exception:
            QMessageBox.warning(self, "Attachment failed", "Could not attach that folder.")
        self._refresh_details_dock()

    def _details_open_attachment(self):
        _aid, path = self.details_panel.selected_attachment()
        if not path:
            return
        url = QUrl.fromLocalFile(path)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "Open failed", f"Could not open:\n{path}")

    def _details_remove_attachment(self):
        aid, _path = self.details_panel.selected_attachment()
        if aid is None:
            return
        self.model.remove_attachment(int(aid))
        self._refresh_details_dock()

    def _refresh_calendar_markers(self):
        with measure_ui(
            "main._refresh_calendar_markers",
            visible=bool(
                hasattr(self, "calendar_dock")
                and self.calendar_dock.isVisible()
            ),
        ):
            if not hasattr(self, "calendar"):
                return
            if hasattr(self, "calendar_dock") and not self.calendar_dock.isVisible():
                return
            if not self._db_available():
                self.calendar.set_completion_summary({})
                return
            try:
                year = int(self.calendar.yearShown())
                month = int(self.calendar.monthShown())
                start = date(year, month, 1)
                if month == 12:
                    end = date(year + 1, 1, 1) - timedelta(days=1)
                else:
                    end = date(year, month + 1, 1) - timedelta(days=1)
                rows = self.db.fetch_due_date_completion_summary(
                    start_due_iso=start.isoformat(),
                    end_due_iso=end.isoformat(),
                    include_archived=False,
                )
                by_date = {
                    str(r.get("due_date") or ""): float(r.get("percent") or 0.0)
                    for r in rows
                }
                self.calendar.set_completion_summary(by_date)
            except Exception:
                self.calendar.set_completion_summary({})

    def _on_undo_stack_index_changed(self, _index: int):
        self._refresh_details_dock()
        self._refresh_calendar_list()
        self._schedule_calendar_marker_refresh()
        self._schedule_review_panel_refresh()
        self._schedule_analytics_panel_refresh()
        self._schedule_row_action_button_update()

    def _refresh_calendar_list(self):
        if not hasattr(self, "calendar_list"):
            return
        self.calendar_list.clear()
        if not self._db_available():
            if hasattr(self, "calendar_list_stack"):
                self.calendar_list_stack.set_has_content(False)
            return
        day_iso = self.calendar.selectedDate().toString("yyyy-MM-dd")
        for task in self.db.fetch_tasks_due_on(day_iso, include_archived=False):
            txt = f"[P{task.get('priority', '')}] {task.get('description', '')} ({task.get('status', '')})"
            it = QListWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, int(task["id"]))
            self.calendar_list.addItem(it)
        if hasattr(self, "calendar_list_stack"):
            self.calendar_list_stack.set_has_content(self.calendar_list.count() > 0)

    def _on_calendar_task_activated(self, item):
        if not item:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        try:
            tid = int(tid)
        except Exception:
            return
        self._focus_task_by_id(tid)

    def _calendar_bucket_for_date(self, qdate):
        try:
            selected = date(qdate.year(), qdate.month(), qdate.day())
        except Exception:
            return "inbox"
        today = date.today()
        if selected == today:
            return "today"
        if selected > today:
            return "upcoming"
        return "inbox"

    def _focus_and_edit_task_by_id(self, task_id: int, allow_perspective_fallback: bool = False) -> bool:
        src = self._source_index_for_task_id(int(task_id), 0)
        if not src.isValid():
            return False
        pidx = self.proxy.mapFromSource(src)
        if not pidx.isValid() and allow_perspective_fallback:
            self._set_perspective_by_key("all")
            pidx = self.proxy.mapFromSource(src)
        if not pidx.isValid():
            return False
        self._expand_proxy_ancestors(pidx)
        self.view.setCurrentIndex(pidx)
        self.view.scrollTo(pidx)
        QTimer.singleShot(0, self._edit_current_cell)
        return True

    def _on_calendar_date_activated(self, qdate):
        if not qdate or not qdate.isValid():
            return
        due_iso = qdate.toString("yyyy-MM-dd")
        bucket = self._calendar_bucket_for_date(qdate)
        ok = self.model.add_task_with_values(
            description="",
            due_date=due_iso,
            priority=None,
            parent_id=None,
            planned_bucket=bucket,
        )
        if not ok:
            return
        self.calendar.setSelectedDate(qdate)
        self._refresh_calendar_list()
        new_id = self.model.last_added_task_id()
        if new_id is None:
            return

        def _finish_focus():
            if self._focus_and_edit_task_by_id(int(new_id), allow_perspective_fallback=True):
                return
            self.statusBar().showMessage(
                "Task created from calendar, but hidden by the current filters.",
                4000,
            )

        QTimer.singleShot(0, _finish_focus)

    def _refresh_review_panel(
        self,
        waiting_days: int | None = None,
        stalled_days: int | None = None,
        recent_days: int | None = None,
    ):
        with measure_ui(
            "main._refresh_review_panel",
            visible=bool(
                hasattr(self, "review_dock")
                and self.review_dock.isVisible()
            ),
        ):
            if not hasattr(self, "review_panel"):
                return
            if hasattr(self, "review_dock") and not self.review_dock.isVisible():
                return
            if not self._db_available():
                self.review_panel.set_review_data({})
                return
            if waiting_days is None:
                waiting_days = int(self.review_panel.waiting_days.value())
            if stalled_days is None:
                stalled_days = int(self.review_panel.stalled_days.value())
            if recent_days is None:
                recent_days = int(self.review_panel.recent_days.value())
            try:
                data = self.model.fetch_review_data(
                    waiting_days=int(waiting_days),
                    stalled_days=int(stalled_days),
                    recent_days=int(recent_days),
                )
            except Exception as e:
                QMessageBox.warning(self, "Review refresh failed", str(e))
                return
            filtered, hidden_counts = filter_acknowledged_review_data(data, self._review_ack_state())
            self.review_panel.set_review_data(filtered, hidden_counts=hidden_counts)

    def _review_ack_state(self) -> dict[str, set[str]]:
        raw = self.model.settings.value("review/acknowledged", "")
        return review_ack_state_from_setting(raw)

    def _save_review_ack_state(self, state: dict[str, set[str]]):
        self.model.settings.setValue("review/acknowledged", review_ack_state_to_setting(state))

    def _review_focus_task(self, task_id: int):
        tid = int(task_id)
        if tid <= 0:
            return
        self._focus_task_by_id(tid)
        self.details_dock.show()
        self._toggle_details_act.setChecked(True)
        self._refresh_details_dock()

    def _review_mark_done(self, task_ids: list[int]):
        ids = [int(x) for x in (task_ids or []) if int(x) > 0]
        if not ids:
            return
        status_col = self._column_index_for_key("status")
        if status_col is None:
            return
        self.model.undo_stack.beginMacro("Review mark done")
        try:
            for tid in ids:
                src = self._source_index_for_task_id(int(tid), status_col)
                if src.isValid():
                    self.model.setData(src, "Done", Qt.ItemDataRole.EditRole)
        finally:
            self.model.undo_stack.endMacro()
        self._refresh_review_panel()

    def _review_archive(self, task_ids: list[int]):
        ids = [int(x) for x in (task_ids or []) if int(x) > 0]
        if not ids:
            return
        self.model.archive_tasks(ids)
        self._refresh_details_dock()
        self._refresh_calendar_list()
        self._refresh_review_panel()

    def _review_restore(self, task_ids: list[int]):
        ids = [int(x) for x in (task_ids or []) if int(x) > 0]
        if not ids:
            return
        self._restore_from_archive_ids(ids)
        self._refresh_review_panel()

    def _review_acknowledge(self, category: str, review_keys: list[str]):
        keys = [str(item or "").strip() for item in (review_keys or []) if str(item or "").strip()]
        if not keys:
            return
        state = acknowledge_review_items(self._review_ack_state(), category, keys)
        self._save_review_ack_state(state)
        self._refresh_review_panel()
        self.statusBar().showMessage(f"Marked {len(keys)} review item(s) as handled.", 2500)

    def _review_clear_acknowledged(self, category: str):
        state = clear_review_acknowledgements(self._review_ack_state(), category=category)
        self._save_review_ack_state(state)
        self._refresh_review_panel()
        self.statusBar().showMessage("Cleared handled state for current review category.", 2500)

    def _review_use_category(self, category: str):
        key = str(category or "").strip()
        if not key:
            return
        if key in PM_REVIEW_CATEGORIES:
            focus_ids = self.review_panel.selected_task_ids()
            if focus_ids:
                self._focus_task_by_id(int(focus_ids[0]))
            self.project_dock.show()
            self._toggle_project_act.setChecked(True)
            self._refresh_project_panel()
            self.statusBar().showMessage(
                "Opened the project cockpit for the selected PM review item.",
                3000,
            )
            return
        state = self._capture_filter_state()
        state["search_text"] = ""
        panel_state = state["filter_panel"] or {}
        panel_state.update(
            {
                "hide_done": True,
                "overdue_only": False,
                "blocked_only": False,
                "waiting_only": False,
            }
        )
        perspective = "all"
        search = ""

        if key == "overdue":
            panel_state["overdue_only"] = True
        elif key == "inbox_unprocessed":
            perspective = "inbox"
        elif key == "waiting_old":
            panel_state["waiting_only"] = True
        elif key in {"recent_done_archived", "archive_roots"}:
            perspective = "completed"
            panel_state["hide_done"] = False
        elif key == "no_due":
            search = "due:none"
        elif key == "blocked_projects":
            search = "is:blocked has:children"
        elif key == "projects_no_next":
            search = "has:children"
        elif key == "recurring_attention":
            search = "is:recurring"

        state["filter_panel"] = panel_state
        state["perspective"] = perspective
        state["search_text"] = search
        self._apply_filter_state(state)
        self.statusBar().showMessage("Applied best-effort main view for the current review category.", 3000)

    def _focus_current_summary(self, details: dict | None = None) -> str:
        if details is None:
            details = self._selected_task_details()
        if not details:
            return "Current selection: none"
        desc = str(details.get("description") or "").strip() or "(untitled task)"
        status = str(details.get("status") or "")
        priority = str(details.get("priority") or "")
        bucket = str(details.get("planned_bucket") or "")
        return f"Current selection: [P{priority}] {desc} | {status} | bucket: {bucket}"

    def _refresh_focus_panel(self, include_waiting: bool | None = None):
        with measure_ui(
            "main._refresh_focus_panel",
            visible=bool(
                hasattr(self, "focus_dock")
                and self.focus_dock.isVisible()
            ),
        ):
            if not hasattr(self, "focus_panel"):
                return
            if hasattr(self, "focus_dock") and not self.focus_dock.isVisible():
                return
            if not self._db_available():
                self.focus_panel.set_focus_data([], "Current selection: none", None)
                return
            if include_waiting is None:
                include_waiting = bool(self.focus_panel.include_waiting.isChecked())
            else:
                self.focus_panel.include_waiting.blockSignals(True)
                self.focus_panel.include_waiting.setChecked(bool(include_waiting))
                self.focus_panel.include_waiting.blockSignals(False)
            try:
                rows = self.model.fetch_focus_data(include_waiting=bool(include_waiting), limit=40)
            except Exception as e:
                QMessageBox.warning(self, "Focus refresh failed", str(e))
                return
            self.focus_panel.set_focus_data(
                rows,
                self._focus_current_summary(self._active_task_details),
                self._active_task_id,
            )

    def _focus_panel_focus_task(self, task_id: int):
        tid = int(task_id)
        if tid <= 0:
            return
        self._focus_task_by_id(tid)
        self._refresh_focus_panel()

    def _focus_panel_open_details(self, task_id: int):
        self._focus_panel_focus_task(task_id)
        self._show_details_and_focus()

    def _refresh_analytics_panel(self, trend_days: int | None = None, tag_days: int | None = None):
        with measure_ui(
            "main._refresh_analytics_panel",
            visible=bool(
                hasattr(self, "analytics_dock")
                and self.analytics_dock.isVisible()
            ),
        ):
            if not hasattr(self, "analytics_panel"):
                return
            if hasattr(self, "analytics_dock") and not self.analytics_dock.isVisible():
                return
            if not self._db_available():
                self.analytics_panel.set_analytics_data({})
                return
            if trend_days is None:
                trend_days = int(self.analytics_panel.trend_days.value())
            if tag_days is None:
                tag_days = int(self.analytics_panel.tag_days.value())
            try:
                data = self.model.fetch_analytics_summary(trend_days=int(trend_days), tag_days=int(tag_days))
            except Exception as e:
                QMessageBox.warning(self, "Analytics refresh failed", str(e))
                return
            self.analytics_panel.set_analytics_data(data)

    def _on_search_changed(self, text: str):
        self.proxy.set_search_text(text)
        self._update_dragdrop_mode()
        self._refresh_task_browser()
        self._schedule_row_action_button_update()

    def _apply_filters(self):
        statuses = self.filter_panel.status_allowed()
        pmin, pmax = self.filter_panel.priority_range()
        dfrom, dto = self.filter_panel.due_range()

        self.proxy.set_status_allowed(statuses)
        self.proxy.set_priority_range(pmin, pmax)
        self.proxy.set_due_range(dfrom, dto)
        self.proxy.set_hide_done(self.filter_panel.hide_done())
        self.proxy.set_overdue_only(self.filter_panel.overdue_only())
        self.proxy.set_blocked_only(self.filter_panel.blocked_only())
        self.proxy.set_waiting_only(self.filter_panel.waiting_only())
        self.proxy.set_show_children_of_matches(self.filter_panel.show_children_of_matches())
        self.proxy.set_tag_filter(self.filter_panel.tag_filter())

        self._update_dragdrop_mode()
        self._refresh_task_browser()
        self._schedule_row_action_button_update()

    def _update_dragdrop_mode(self):
        active = self.proxy.is_filter_active() or not self.proxy.is_manual_sort_mode()
        self._set_dragdrop_enabled(not active)

    def _set_dragdrop_enabled(self, enabled: bool):
        if enabled:
            self.view.setDragEnabled(True)
            self.view.setAcceptDrops(True)
            self.view.viewport().setAcceptDrops(True)
            self.view.setDropIndicatorShown(True)
            self.view.setDragDropMode(QTreeView.DragDropMode.InternalMove)
            self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        else:
            self.view.setDragEnabled(False)
            # Keep external file drops enabled for attachments.
            self.view.setAcceptDrops(True)
            self.view.viewport().setAcceptDrops(True)
            self.view.setDropIndicatorShown(False)
            self.view.setDragDropMode(QTreeView.DragDropMode.NoDragDrop)

    def _poll_reminders(self):
        if self._reminder_dialog_open:
            return
        if self._reminder_mode == self.REMINDER_MODE_MUTE_ALL:
            return
        if self._reminder_prompt_cooldown_until is not None and datetime.now() < self._reminder_prompt_cooldown_until:
            return
        try:
            pending = self.model.fetch_pending_reminders(limit=10)
        except Exception:
            return
        if self._reminder_mode == self.REMINDER_MODE_PRIORITY1_ONLY:
            pending = [r for r in pending if int(r.get("priority") or 0) == 1]
        if not pending:
            return
        pending.sort(key=lambda r: (str(r.get("reminder_at") or ""), int(r.get("priority") or 99), int(r.get("id") or 0)))

        dlg = ReminderBatchDialog(pending, self)
        self._reminder_dialog_open = True
        try:
            if dlg.exec() != dlg.DialogCode.Accepted:
                self._reminder_prompt_cooldown_until = datetime.now() + timedelta(minutes=2)
                return

            action = dlg.action()
            if action == ReminderBatchDialog.ACTION_ACK:
                self.model.undo_stack.beginMacro("Acknowledge reminders")
                try:
                    for r in pending:
                        try:
                            self.model.mark_reminder_fired(int(r["id"]))
                        except Exception:
                            continue
                finally:
                    self.model.undo_stack.endMacro()
                self._reminder_prompt_cooldown_until = None
                return

            if action == ReminderBatchDialog.ACTION_SNOOZE:
                snooze_iso = dlg.snooze_iso()
                self.model.undo_stack.beginMacro("Snooze reminders")
                try:
                    for r in pending:
                        try:
                            mins = r.get("reminder_minutes_before")
                            mins = int(mins) if mins is not None else None
                        except Exception:
                            mins = None
                        try:
                            self.model.set_task_reminder(int(r["id"]), snooze_iso, mins)
                        except Exception:
                            continue
                finally:
                    self.model.undo_stack.endMacro()
                self._reminder_prompt_cooldown_until = None
                return
            self._reminder_prompt_cooldown_until = datetime.now() + timedelta(minutes=2)
        finally:
            self._reminder_dialog_open = False

    def _configure_auto_backup_timer(self):
        mins = self.model.settings.value("backup/interval_minutes", 30, type=int)
        if mins is None or int(mins) <= 0:
            self._auto_backup_timer.stop()
            return
        self._auto_backup_timer.start(int(mins) * 60_000)

    def _run_auto_backup(self):
        try:
            keep = self.model.settings.value("backup/keep_count", 20, type=int)
            path = create_versioned_backup(self.db, "auto")
            rotate_backups(max_keep=int(keep or 20), db_path=self.db.path)
            self.model.settings.setValue("backup/last_snapshot_path", str(path))
            self.model.settings.setValue("backup/last_snapshot_at", datetime.now().isoformat(timespec="seconds"))
            log_event(
                "Automatic snapshot created",
                context="backup.auto",
                db_path=self.db.path,
                details={"path": str(path), "keep_count": int(keep or 20)},
            )
        except Exception as e:
            log_exception(e, context="auto-backup", db_path=self.db.path)
            # Intentionally silent; backup failures should not interrupt app flow.
            return

    def _auto_backup_settings_prompt(self):
        mins = self.model.settings.value("backup/interval_minutes", 30, type=int)
        keep = self.model.settings.value("backup/keep_count", 20, type=int)
        on_close = self.model.settings.value("backup/on_close", True, type=bool)

        new_mins, ok = QInputDialog.getInt(
            self,
            "Auto backup interval",
            "Minutes (0 disables):",
            int(mins or 30),
            0,
            24 * 60,
            5,
        )
        if not ok:
            return
        new_keep, ok = QInputDialog.getInt(
            self,
            "Backup rotation",
            "Keep latest snapshots:",
            int(keep or 20),
            1,
            500,
            1,
        )
        if not ok:
            return
        keep_close, ok = QInputDialog.getItem(
            self,
            "Backup on exit",
            "Create snapshot when closing app:",
            ["Yes", "No"],
            0 if on_close else 1,
            False,
        )
        if not ok:
            return

        self.model.settings.setValue("backup/interval_minutes", int(new_mins))
        self.model.settings.setValue("backup/keep_count", int(new_keep))
        self.model.settings.setValue("backup/on_close", keep_close == "Yes")
        self._configure_auto_backup_timer()
        log_event(
            "Automatic backup settings updated",
            context="backup.settings",
            db_path=self.db.path,
            details={
                "interval_minutes": int(new_mins),
                "keep_count": int(new_keep),
                "backup_on_close": bool(keep_close == "Yes"),
            },
        )

    def _create_backup_now(self):
        try:
            path = create_versioned_backup(self.db, "manual")
            keep = self.model.settings.value("backup/keep_count", 20, type=int)
            rotate_backups(max_keep=int(keep or 20), db_path=self.db.path)
            self.model.settings.setValue("backup/last_snapshot_path", str(path))
            self.model.settings.setValue("backup/last_snapshot_at", datetime.now().isoformat(timespec="seconds"))
            log_event(
                "Manual snapshot created",
                context="backup.manual",
                db_path=self.db.path,
                details={"path": str(path), "keep_count": int(keep or 20)},
            )
            QMessageBox.information(self, "Backup created", f"Snapshot saved to:\n{path}")
        except Exception as e:
            log_exception(e, context="manual-backup", db_path=self.db.path)
            QMessageBox.warning(self, "Backup failed", str(e))

    def _open_snapshot_history_dialog(self):
        dlg = SnapshotHistoryDialog(self.db, self.workspace_manager, self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.switch_workspace_id():
            self._switch_to_workspace(str(dlg.switch_workspace_id()))

    def _open_workspace_manager(self):
        dlg = WorkspaceManagerDialog(self.workspace_manager, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        target_workspace_id = dlg.switch_workspace_id()
        if target_workspace_id:
            self._switch_to_workspace(str(target_workspace_id))

    def _export_backup_data(self):
        log_event("Backup export opened", context="backup.export", db_path=self.db.path)
        export_backup_ui(self, self.db)

    def _import_backup_data(self):
        log_event("Backup import opened", context="backup.import", db_path=self.db.path)
        import_backup_ui(self)

    def _export_themes(self):
        log_event("Theme export opened", context="theme.export", db_path=self.db.path)
        export_themes_ui(self, self.model.settings)

    def _import_themes(self):
        log_event("Theme import opened", context="theme.import", db_path=self.db.path)
        import_themes_ui(
            self,
            self.model.settings,
            apply_callback=lambda: self._apply_theme_now(),
        )

    def _save_ui_settings(self):
        s = self.model.settings
        s.setValue("ui/geometry", self.saveGeometry())
        s.setValue("ui/window_state", self.saveState())
        s.setValue("ui/header_state", self.view.header().saveState())
        s.setValue("ui/controls_dock_visible", self.controls_dock.isVisible())
        s.setValue("ui/tree_visible", self._is_task_table_visible())
        s.setValue("ui/tree_floating", self._is_task_table_floating())
        if self._floating_table_window is not None:
            s.setValue("ui/tree_float_geometry", self._floating_table_window.saveGeometry())
        s.setValue("ui/filters_dock_visible", self.filter_dock.isVisible())
        s.setValue("ui/details_dock_visible", self.details_dock.isVisible())
        s.setValue("ui/project_dock_visible", self.project_dock.isVisible())
        s.setValue("ui/relationships_dock_visible", self.relationships_dock.isVisible())
        s.setValue("ui/undo_dock_visible", self.undo_dock.isVisible())
        s.setValue("ui/focus_dock_visible", self.focus_dock.isVisible())
        s.setValue("ui/calendar_dock_visible", self.calendar_dock.isVisible())
        s.setValue("ui/review_dock_visible", self.review_dock.isVisible())
        s.setValue("ui/analytics_dock_visible", self.analytics_dock.isVisible())
        s.setValue("ui/tooltips_enabled", self._tooltips_enabled)
        s.setValue("ui/perspective", str(self.view_mode.currentData() or "all"))
        s.setValue("ui/sort_mode", str(self.sort_mode.currentData() or "manual"))
        s.setValue("ui/reminder_mode", self._reminder_mode)
        self.workspace_manager.save_state_for(self.workspace_id)

    def _switch_to_workspace(self, workspace_id: str):
        target_id = str(workspace_id or "").strip()
        if not target_id or target_id == self.workspace_id:
            return
        try:
            log_event(
                "Workspace switch requested",
                context="workspace.switch",
                db_path=self.db.path,
                details={"from_workspace": self.workspace_id, "to_workspace": target_id},
            )
            self._save_ui_settings()
            self._workspace_switching = True
            self.workspace_manager.set_current_workspace(target_id, apply_state=True)
            replacement = MainWindow(self.workspace_manager, target_id)
            self._replacement_window = replacement
            replacement.show()
            log_event(
                "Workspace switch completed",
                context="workspace.switch",
                db_path=self.db.path,
                details={"from_workspace": self.workspace_id, "to_workspace": target_id},
            )
            self.close()
        except Exception as e:
            self._workspace_switching = False
            log_exception(e, context="workspace-switch", db_path=self.db.path)
            QMessageBox.warning(self, "Workspace switch failed", str(e))

    def _capture_filter_state(self) -> dict:
        return {
            "search_text": self.search.text(),
            "filter_panel": self.filter_panel.snapshot(),
            "perspective": str(self.view_mode.currentData() or "all"),
            "sort_mode": str(self.sort_mode.currentData() or "manual"),
        }

    def _apply_filter_state(self, state: dict):
        data = state or {}
        self.search.setText(str(data.get("search_text") or ""))
        self.filter_panel.apply_snapshot(data.get("filter_panel") or {})
        self._set_perspective_by_key(str(data.get("perspective") or "all"))
        self._set_sort_mode_by_key(str(data.get("sort_mode") or "manual"))
        self._apply_filters()

    def _saved_view_names(self) -> list[str]:
        return [str(v.get("name")) for v in self.model.list_saved_filter_views() if str(v.get("name") or "").strip()]

    def _save_filter_view_prompt(self):
        name, ok = QInputDialog.getText(self, "Save filter view", "View name:")
        if not ok:
            return
        n = str(name or "").strip()
        if not n:
            return
        try:
            self.model.save_filter_view(n, self._capture_filter_state(), overwrite=True)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    def _load_filter_view_prompt(self):
        names = self._saved_view_names()
        if not names:
            QMessageBox.information(self, "No saved views", "There are no saved filter views.")
            return
        name, ok = QInputDialog.getItem(self, "Load filter view", "View", names, 0, False)
        if not ok or not name:
            return
        state = self.model.load_filter_view(str(name))
        if state is None:
            QMessageBox.warning(self, "Load failed", "Selected view could not be loaded.")
            return
        self._apply_filter_state(state)

    def _update_filter_view_prompt(self):
        names = self._saved_view_names()
        if not names:
            QMessageBox.information(self, "No saved views", "There are no saved filter views.")
            return
        name, ok = QInputDialog.getItem(self, "Update filter view", "View", names, 0, False)
        if not ok or not name:
            return
        try:
            self.model.save_filter_view(str(name), self._capture_filter_state(), overwrite=True)
        except Exception as e:
            QMessageBox.warning(self, "Update failed", str(e))

    def _delete_filter_view_prompt(self):
        names = self._saved_view_names()
        if not names:
            QMessageBox.information(self, "No saved views", "There are no saved filter views.")
            return
        name, ok = QInputDialog.getItem(self, "Delete filter view", "View", names, 0, False)
        if not ok or not name:
            return
        self.model.delete_filter_view(str(name))

    def _save_template_prompt(self):
        tid = self._selected_task_id()
        if tid is None:
            return
        name, ok = QInputDialog.getText(self, "Save template", "Template name:")
        if not ok:
            return
        n = str(name or "").strip()
        if not n:
            return
        try:
            self.model.save_template_from_task(n, int(tid))
        except Exception as e:
            QMessageBox.warning(self, "Template save failed", str(e))

    def _create_from_template_prompt(self):
        templates = self.model.list_templates()
        names = [str(t.get("name")) for t in templates if str(t.get("name") or "").strip()]
        if not names:
            QMessageBox.information(self, "No templates", "There are no saved templates.")
            return
        name, ok = QInputDialog.getItem(self, "Create from template", "Template", names, 0, False)
        if not ok or not name:
            return
        self._create_from_template_name(str(name))

    def _delete_template_prompt(self):
        templates = self.model.list_templates()
        rows_by_name = {
            str(row.get("name") or "").strip(): row
            for row in templates
            if str(row.get("name") or "").strip()
        }
        names = sorted(rows_by_name)
        if not names:
            QMessageBox.information(self, "No templates", "There are no saved templates.")
            return
        name, ok = QInputDialog.getItem(self, "Delete template", "Template", names, 0, False)
        if not ok or not name:
            return
        row = rows_by_name.get(str(name), {})
        created_at = str(row.get("created_at") or "").strip()
        updated_at = str(row.get("updated_at") or "").strip()
        details = []
        if created_at:
            details.append(f"Created: {created_at}")
        if updated_at:
            details.append(f"Updated: {updated_at}")
        message = f"Delete saved template '{str(name)}'?\n\nThis cannot be undone."
        if details:
            message += "\n\n" + "\n".join(details)
        res = QMessageBox.warning(
            self,
            "Delete template",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        self.model.delete_template(str(name))
        log_event(
            "Template deleted",
            context="template.delete",
            db_path=self.db.path,
            details={"template_name": str(name)},
        )

    def _set_status_for_selected_prompt(self):
        ids = self._selected_task_ids()
        if not ids:
            return
        status, ok = QInputDialog.getItem(self, "Set status", "Status", STATUSES, 0, False)
        if not ok or not status:
            return
        status_col = self._column_index_for_key("status")
        if status_col is None:
            return
        self.model.undo_stack.beginMacro("Set status")
        try:
            for tid in ids:
                src = self._source_index_for_task_id(int(tid), status_col)
                if src.isValid():
                    self.model.setData(src, status, Qt.ItemDataRole.EditRole)
        finally:
            self.model.undo_stack.endMacro()

    def _set_priority_for_selected_prompt(self):
        ids = self._selected_task_ids()
        if not ids:
            return
        value, ok = QInputDialog.getInt(self, "Set priority", "Priority (1-5)", 3, 1, 5, 1)
        if not ok:
            return
        priority_col = self._column_index_for_key("priority")
        if priority_col is None:
            return
        self.model.undo_stack.beginMacro("Set priority")
        try:
            for tid in ids:
                src = self._source_index_for_task_id(int(tid), priority_col)
                if src.isValid():
                    self.model.setData(src, int(value), Qt.ItemDataRole.EditRole)
        finally:
            self.model.undo_stack.endMacro()

    def _build_command_palette_commands(self) -> list[PaletteCommand]:
        commands: list[PaletteCommand] = [
            PaletteCommand(
                "ui.quick_capture",
                "Open quick capture",
                "Show the lightweight capture window for fast inbox entry",
                ("capture", "tray", "mini", "inbox"),
                self._open_quick_capture_dialog,
            ),
            PaletteCommand("task.add", "Add task", "Create a new top-level task", ("new", "create", "task"), self._add_task_and_edit),
            PaletteCommand("task.add_child", "Add child task", "Create child under current selection", ("child", "subtask"), self._add_child_to_selected),
            PaletteCommand("task.duplicate", "Duplicate task", "Duplicate selected task", ("clone", "copy"), self._duplicate_selected),
            PaletteCommand(
                "task.duplicate_subtree",
                "Duplicate with children",
                "Duplicate selected subtree",
                ("clone subtree", "copy children"),
                self._duplicate_selected_subtree,
            ),
            PaletteCommand("task.archive", "Archive task", "Archive selected task(s)", ("delete", "hide"), self._archive_selected),
            PaletteCommand("task.delete", "Delete permanently", "Permanently delete selected task(s)", ("remove", "hard delete"), self._delete_selected_permanently),
            PaletteCommand("ui.open_details", "Open details panel", "Show and focus details panel", ("notes", "details"), self._show_details_and_focus),
            PaletteCommand(
                "ui.open_project_cockpit",
                "Open project cockpit",
                "Show project charter, milestones, deliverables, timeline, and workload for the current project",
                ("project", "milestone", "deliverable", "timeline", "gantt"),
                lambda: (self.project_dock.show(), self._toggle_project_act.setChecked(True), self._refresh_project_panel()),
            ),
            PaletteCommand(
                "ui.open_capture_navigation",
                "Open capture/navigation panel",
                "Show the dock that contains quick add, search, sort, and perspective controls",
                ("controls", "search", "quick add", "navigation"),
                self._show_controls_dock,
            ),
            PaletteCommand(
                "ui.toggle_table",
                "Toggle task table",
                "Show or hide the main task table while keeping dock panels active",
                ("table", "tree", "center"),
                self._toggle_task_table_visibility,
            ),
            PaletteCommand(
                "ui.float_table",
                "Float task table",
                "Detach or redock the main task table window",
                ("table", "float", "detach", "monitor"),
                lambda: self._set_task_table_floating(not self._is_task_table_floating()),
            ),
            PaletteCommand("task.set_priority", "Change priority", "Set priority on selected task(s)", ("p1", "p2", "p3"), self._set_priority_for_selected_prompt),
            PaletteCommand("task.set_status", "Change status", "Set status on selected task(s)", ("todo", "done", "blocked"), self._set_status_for_selected_prompt),
            PaletteCommand(
                "ui.open_review",
                "Open review workflow",
                "Show review dock and refresh categories",
                ("review", "weekly review"),
                lambda: (self.review_dock.show(), self._toggle_review_act.setChecked(True), self._refresh_review_panel()),
            ),
            PaletteCommand(
                "ui.open_analytics",
                "Open analytics dashboard",
                "Show analytics dock and refresh metrics",
                ("dashboard", "analytics"),
                lambda: (self.analytics_dock.show(), self._toggle_analytics_act.setChecked(True), self._refresh_analytics_panel()),
            ),
            PaletteCommand(
                "ui.open_focus",
                "Open focus mode",
                "Show the actionable focus shortlist",
                ("focus", "today", "next action"),
                lambda: (self.focus_dock.show(), self._toggle_focus_act.setChecked(True), self._refresh_focus_panel()),
            ),
            PaletteCommand(
                "ui.open_diagnostics",
                "Open diagnostics",
                "Inspect health checks and repair tools",
                ("health", "integrity", "diagnostics"),
                self._open_diagnostics_dialog,
            ),
            PaletteCommand(
                "ui.open_log_viewer",
                "Open application log",
                "View crash entries and operation log history",
                ("log", "logs", "errors", "troubleshooting"),
                self._open_log_viewer_dialog,
            ),
            PaletteCommand(
                "help.quick_start",
                "Open quick start",
                "Show the welcome/onboarding guide",
                ("welcome", "onboarding"),
                self._open_onboarding_dialog,
            ),
            PaletteCommand(
                "workspace.manage",
                "Open workspace profiles",
                "Manage and switch named workspace databases",
                ("workspace", "profile", "database"),
                self._open_workspace_manager,
            ),
            PaletteCommand(
                "snapshot.history",
                "Open snapshot history",
                "Browse local restore points and create restored copies",
                ("snapshot", "backup", "timeline", "history"),
                self._open_snapshot_history_dialog,
            ),
            PaletteCommand(
                "ui.relationships",
                "Open relationship inspector",
                "Show dependencies, same-tag tasks, and project relations",
                ("relationships", "dependencies", "related"),
                lambda: (self.relationships_dock.show(), self._toggle_relationships_act.setChecked(True), self._refresh_relationships_panel()),
            ),
            PaletteCommand(
                "help.quick_add",
                "Open quick-add help",
                "Jump to quick-add syntax in the user guide",
                ("help", "syntax", "quick add"),
                lambda: self._open_help_anchor("quick-add"),
            ),
            PaletteCommand(
                "help.search",
                "Open search help",
                "Jump to advanced search syntax in the user guide",
                ("help", "search syntax", "filters"),
                lambda: self._open_help_anchor("search"),
            ),
            PaletteCommand(
                "help.shortcuts",
                "Open shortcuts help",
                "Jump to the keyboard shortcut overview",
                ("help", "keyboard", "shortcuts"),
                lambda: self._open_help_anchor("shortcuts"),
            ),
            PaletteCommand("ui.focus_search", "Focus search", "Move cursor to search box", ("search", "find"), self._focus_search_input),
            PaletteCommand("ui.focus_quick_add", "Focus quick add", "Move cursor to quick-add input", ("quick add", "capture"), self._focus_quick_add_input),
            PaletteCommand("backup.export_data", "Export backup data", "Open data export dialog", ("backup", "export"), self._export_backup_data),
            PaletteCommand("backup.import_data", "Import backup data", "Open data import dialog", ("backup", "import"), self._import_backup_data),
            PaletteCommand("theme.export", "Export themes", "Open theme export dialog", ("theme", "export"), self._export_themes),
            PaletteCommand(
                "theme.import",
                "Import themes",
                "Open theme import dialog",
                ("theme", "import"),
                self._import_themes,
            ),
        ]

        # Perspective jumps
        for label, key in self._perspectives:
            if key == "all":
                continue
            commands.append(
                PaletteCommand(
                    f"perspective.{key}",
                    f"Go to {label}",
                    "Switch active perspective",
                    ("view", "perspective"),
                    lambda k=key: self._set_perspective_by_key(k),
                )
            )

        # Saved views
        for name in self._saved_view_names():
            commands.append(
                PaletteCommand(
                    f"saved_view.{name}",
                    f"Apply saved view: {name}",
                    "Load stored search/filter state",
                    ("saved view", "filter view"),
                    lambda n=name: self._apply_saved_view_by_name(n),
                )
            )

        # Templates
        templates = self.model.list_templates()
        for row in templates:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            commands.append(
                PaletteCommand(
                    f"template.insert.{name}",
                    f"Insert template: {name}",
                    "Create tasks from template under current selection",
                    ("template", "insert"),
                    lambda n=name: self._create_from_template_name(n),
                )
            )

        return commands

    def _apply_saved_view_by_name(self, name: str):
        state = self.model.load_filter_view(str(name))
        if state is None:
            QMessageBox.warning(self, "Load failed", "Selected view could not be loaded.")
            return
        self._apply_filter_state(state)

    def _create_from_template_name(self, name: str):
        payload = self.model.load_template_payload(str(name))
        if not payload:
            QMessageBox.warning(self, "Template create failed", "Template payload is empty or invalid.")
            return
        placeholders = collect_template_placeholders(payload)
        if placeholders:
            dlg = TemplateVariablesDialog(placeholders, self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            payload = apply_template_values(payload, dlg.values())
        parent_id = self._selected_task_id()
        try:
            new_id = self.model.create_tasks_from_template_payload(payload, parent_id=parent_id)
        except Exception as e:
            QMessageBox.warning(self, "Template create failed", str(e))
            return
        if new_id:
            self._focus_task_by_id(int(new_id))
            self._refresh_calendar_list()

    def _show_details_and_focus(self):
        self.details_dock.show()
        self._toggle_details_act.setChecked(True)
        self._refresh_details_dock()
        try:
            self.details_panel.notes.setFocus()
        except Exception:
            pass

    def _open_command_palette(self):
        commands = self._build_command_palette_commands()
        dlg = CommandPaletteDialog(commands, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        selected = dlg.selected_command_id()
        if not selected:
            return
        for cmd in commands:
            if cmd.command_id == selected and callable(cmd.action):
                cmd.action()
                return

    # ---------- Help + tooltips ----------
    def _set_action_help(self, action: QAction, text: str):
        tip = str(text or "").strip()
        if not tip:
            return
        shortcut_text = ""
        try:
            sequences = action.shortcuts()
            if sequences:
                shortcut_text = " / ".join(
                    shortcut_display_text(seq) for seq in sequences if shortcut_display_text(seq)
                )
            elif not action.shortcut().isEmpty():
                shortcut_text = shortcut_display_text(action.shortcut())
        except Exception:
            shortcut_text = ""
        if shortcut_text:
            tip = f"{tip} Shortcut: {shortcut_text}."
        action.setToolTip(tip)
        action.setStatusTip(tip)
        action.setWhatsThis(tip)

    def _fallback_tooltip_for_widget(self, w: QWidget) -> str:
        cls = w.metaObject().className()
        if cls == "QLineEdit":
            placeholder = ""
            try:
                placeholder = str(w.placeholderText() or "").strip()
            except Exception:
                placeholder = ""
            return placeholder if placeholder else "Enter text."
        if cls == "QComboBox":
            return "Choose one option from this list."
        if cls in {"QPushButton", "QToolButton"}:
            try:
                txt = str(w.text() or "").strip()
            except Exception:
                txt = ""
            return f"Click to {txt.lower()}." if txt else "Click this button to run an action."
        if cls == "QTreeView":
            return "Task tree. Select rows, edit values, and manage hierarchy."
        if cls in {"QListWidget", "QUndoView"}:
            return "List view."
        if cls == "QCalendarWidget":
            return "Select a date to inspect due tasks."
        if cls == "QDateTimeEdit":
            return "Pick date and time."
        if cls == "QSpinBox":
            return "Adjust a numeric value."
        if cls == "QCheckBox":
            return "Toggle this option on or off."
        if cls == "QTextBrowser":
            return "Help/document content area."
        if cls == "QDockWidget":
            return "Dock panel. You can move or hide it from the View menu."
        if cls == "QLabel":
            try:
                txt = str(w.text() or "").strip()
            except Exception:
                txt = ""
            if txt:
                return f"{txt} information."
            return "Informational label."
        return "Interface control."

    def _apply_widget_tooltips(self):
        explicit: list[tuple[QWidget, str]] = [
            (
                self.quick_add,
                f"Quick-add task input. Supports inline tags, bucket commands, planning phrases, and natural due dates. Focus shortcut: {shortcut_display_text('Ctrl+L')}.",
            ),
            (
                self.search,
                f"Search tasks with free text and operators like status:, due<=, tag:, has:. Focus shortcut: {shortcut_display_text('Ctrl+F')}.",
            ),
            (self.controls_panel, "Capture and navigation controls for quick add, search, perspective changes, and sort mode."),
            (self.view_mode, "Choose a built-in perspective: All, Today, Upcoming, Inbox, Someday, Completed/Archive."),
            (self.sort_mode, "Choose how tasks are sorted in the current view."),
            (self.view, "Main task tree. Select rows, edit cells, and organize hierarchy."),
            (self.row_add_btn, "Add child task to the focused row."),
            (self.row_del_btn, "Archive focused row."),
            (self.filter_panel, "Advanced filtering controls."),
            (self.details_panel, "Task details editor with side-panel browsing, notes, tags, recurrence, reminders, and attachments."),
            (self.relationships_panel, "Relationship inspector for dependencies, same-tag tasks, same-project tasks, and project health context."),
            (self.undo_view, "Undo history list. Click an entry to inspect/step through history."),
            (self.calendar, "Calendar navigator for due-date agenda."),
            (self.calendar_list, "Tasks due on selected calendar date."),
            (self.review_panel, "Guided weekly/daily review workspace with actionable categories."),
            (self.focus_panel, "Focus mode shortlist for overdue, today, and next-action tasks."),
            (self.analytics_panel, "Completion and workload analytics dashboard."),
        ]

        for widget, tip in explicit:
            widget.setToolTip(tip)
            widget.setStatusTip(tip)
            widget.setWhatsThis(tip)

        for w in self.findChildren(QWidget):
            current = str(w.toolTip() or "").strip()
            if current:
                continue
            tip = self._fallback_tooltip_for_widget(w)
            if tip:
                w.setToolTip(tip)
                w.setStatusTip(tip)
                w.setWhatsThis(tip)

    def _set_tooltips_enabled(self, enabled: bool, show_message: bool = True):
        self._tooltips_enabled = bool(enabled)
        if hasattr(self, "_toggle_tooltips_act"):
            self._toggle_tooltips_act.blockSignals(True)
            self._toggle_tooltips_act.setChecked(self._tooltips_enabled)
            self._toggle_tooltips_act.blockSignals(False)
        self.model.settings.setValue("ui/tooltips_enabled", self._tooltips_enabled)
        if show_message:
            if self._tooltips_enabled:
                self.statusBar().showMessage("Tooltips enabled.", 2000)
            else:
                self.statusBar().showMessage("Tooltips disabled.", 2000)

    def _open_help_dialog(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _open_help_anchor(self, anchor: str):
        self._open_help_dialog()
        if self._help_dialog is not None:
            self._help_dialog.open_anchor(anchor)

    def _open_about_dialog(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            (
                f"<h3>{APP_NAME} {app_display_version()}</h3>"
                "<p>Local-first personal task and project management for a "
                "single desktop user.</p>"
                "<p>No cloud sync, no accounts, no telemetry, and no required "
                "online services.</p>"
                f"<p><strong>Workspace data:</strong> {self._workspace_data_path()}</p>"
                f"<p><strong>Current workspace:</strong> {self.workspace_name}</p>"
            ),
        )

    def _open_diagnostics_dialog(self):
        if self._diagnostics_dialog is None:
            self._diagnostics_dialog = DiagnosticsDialog(
                self.db,
                theme_name_provider=lambda: self.model.theme_mgr.current_theme_name(),
                workspace_name_provider=lambda: self.workspace_name,
                workspace_path_provider=self._workspace_data_path,
                parent=self,
            )
        self._diagnostics_dialog.refresh_report()
        self._diagnostics_dialog.show()
        self._diagnostics_dialog.raise_()
        self._diagnostics_dialog.activateWindow()

    def _open_log_viewer_dialog(self):
        if self._log_viewer_dialog is None:
            self._log_viewer_dialog = LogViewerDialog(self)
        self._log_viewer_dialog.refresh()
        self._log_viewer_dialog.show()
        self._log_viewer_dialog.raise_()
        self._log_viewer_dialog.activateWindow()

    def _workspace_data_path(self) -> str:
        try:
            return str(Path(self.workspace_db_path).expanduser().resolve().parent)
        except Exception:
            return str(app_data_dir())

    def _update_window_title(self):
        self.setWindowTitle(f"{APP_NAME} - {self.workspace_name}")
        if self._floating_table_window is not None:
            self._floating_table_window.setWindowTitle(f"{APP_NAME} - {self.workspace_name} - Task table")

    def _init_status_bar(self):
        self._version_label = QLabel(app_display_version(), self)
        self._version_label.setObjectName("AppVersionLabel")
        self._version_label.setToolTip(f"{APP_NAME} {app_display_version()}")
        self._version_label.setStatusTip("Application version.")
        self.statusBar().addPermanentWidget(self._version_label)
        self._active_task_label = QLabel("Active task: none", self)
        self._active_task_label.setObjectName("ActiveTaskStatusLabel")
        self._active_task_label.setToolTip("Current active task selection.")
        self._active_task_label.setStatusTip("Current active task selection.")
        self.statusBar().addPermanentWidget(self._active_task_label)
        self._workspace_label = QLabel(f"Workspace: {self.workspace_name}", self)
        self._workspace_label.setObjectName("WorkspaceStatusLabel")
        self._workspace_label.setToolTip(self.workspace_db_path)
        self._workspace_label.setStatusTip("Current workspace profile and database path.")
        self.statusBar().addPermanentWidget(self._workspace_label)
        self.statusBar().showMessage(
            f"Ready. {APP_NAME} {app_display_version()} | Workspace: {self.workspace_name}",
            3000,
        )

    def _apply_accessibility_metadata(self):
        named_widgets: list[tuple[QWidget, str, str]] = [
            (self.quick_add, "Quick add input", "Enter a task or planning command with optional tags, bucket directives, due dates, and priority."),
            (self.search, "Task search input", "Search tasks with free text and structured operators."),
            (self.controls_panel, "Capture and navigation panel", "Dockable panel with quick add, search, perspectives, and sort controls."),
            (self.view, "Task tree", "Primary tree view for tasks, hierarchy, and inline editing."),
            (self.view_mode, "Perspective selector", "Switch between All, Today, Upcoming, Inbox, Someday, and Completed."),
            (self.sort_mode, "Sort mode selector", "Choose the current task sorting mode."),
            (self.filter_panel, "Filters panel", "Advanced filtering options for the task tree."),
            (self.details_panel, "Task details panel", "Browse tasks from the side panel and edit notes, tags, recurrence, reminders, and attachments."),
            (self.relationships_panel, "Relationship inspector", "Inspect dependencies, related tasks, and project context for the selected task."),
            (self.review_panel, "Review workflow panel", "Guided weekly review tabs with direct task actions."),
            (self.focus_panel, "Focus mode panel", "Short actionable list for focused work sessions."),
            (self.analytics_panel, "Analytics panel", "Lightweight completion and planning summary."),
            (self.calendar, "Calendar navigator", "Monthly calendar with due-date activity markers."),
        ]
        for widget, name, description in named_widgets:
            widget.setAccessibleName(name)
            widget.setAccessibleDescription(description)

    def _task_count(self) -> int:
        try:
            return len(self.db.fetch_tasks())
        except Exception:
            return 0

    def _maybe_show_onboarding(self):
        completed = self.model.settings.value("ui/onboarding_completed", False, type=bool)
        task_count = self._task_count()
        if not should_show_onboarding(bool(completed), int(task_count)):
            if int(task_count) > 0 and not bool(completed):
                self.model.settings.setValue("ui/onboarding_completed", True)
            return
        self._open_onboarding_dialog(force=True)

    def _load_demo_data(self):
        if self._task_count() > 0:
            QMessageBox.information(self, "Demo data not loaded", "Demo data is only added to an empty task list.")
            return
        try:
            summary = populate_demo_database(self.db, today=date.today())
        except Exception as e:
            log_exception(e, context="demo-data-load", db_path=self.db.path)
            QMessageBox.warning(self, "Demo data not loaded", str(e))
            return
        log_event(
            "Demo dataset loaded into current workspace",
            context="demo.load",
            db_path=self.db.path,
            details={"task_count": int(summary.get("task_count") or 0)},
        )

        self.model.reload_all(reset_header_state=False)
        self._set_perspective_by_key("all")
        self._refresh_review_panel()
        self._refresh_focus_panel()
        self._refresh_calendar_list()
        self._refresh_calendar_markers()
        self._refresh_analytics_panel()
        self._refresh_details_dock()
        self._refresh_relationships_panel()
        self.statusBar().showMessage(
            f"Loaded demo dataset with {int(summary.get('task_count') or 0)} tasks.",
            3500,
        )

    def _open_demo_workspace(self):
        try:
            result = create_demo_workspace(self.workspace_manager, today=date.today())
        except Exception as e:
            log_exception(e, context="demo-workspace-create", db_path=self.db.path)
            QMessageBox.warning(self, "Demo workspace failed", str(e))
            return
        workspace = result.get("workspace") or {}
        summary = result.get("summary") or {}
        log_event(
            "Demo workspace created",
            context="demo.workspace",
            db_path=self.db.path,
            details={
                "workspace_id": str(workspace.get("id") or ""),
                "workspace_name": str(workspace.get("name") or ""),
                "task_count": int(summary.get("task_count") or 0),
            },
        )
        self.statusBar().showMessage(
            f"Created demo workspace '{str(workspace.get('name') or '')}' with {int(summary.get('task_count') or 0)} tasks.",
            3500,
        )
        self._switch_to_workspace(str(workspace.get("id") or ""))

    def _open_onboarding_dialog(self, force: bool = False):
        can_load_demo = self._task_count() == 0
        if not force and not can_load_demo:
            self.model.settings.setValue("ui/onboarding_completed", True)
        dlg = WelcomeDialog(can_load_demo=can_load_demo, can_create_demo_workspace=True, parent=self)
        result = dlg.exec()
        if result == dlg.DialogCode.Accepted:
            self.model.settings.setValue("ui/onboarding_completed", bool(dlg.remember.isChecked()))
            action = dlg.action()
            if action == WelcomeDialog.ACTION_DEMO:
                self._load_demo_data()
            elif action == WelcomeDialog.ACTION_DEMO_WORKSPACE:
                self._open_demo_workspace()
            elif action == WelcomeDialog.ACTION_HELP:
                self._open_help_anchor("overview")
            elif action == WelcomeDialog.ACTION_REVIEW:
                self.review_dock.show()
                self._toggle_review_act.setChecked(True)
                self._refresh_review_panel()
        else:
            self.model.settings.setValue("ui/onboarding_completed", bool(dlg.remember.isChecked()))

    def _ensure_quick_capture_dialog(self) -> QuickCaptureDialog:
        if self._quick_capture_dialog is None:
            dlg = QuickCaptureDialog(self)
            dlg.captureRequested.connect(self._on_quick_capture_requested)
            dlg.revealRequested.connect(self._show_main_window)
            self._quick_capture_dialog = dlg
        return self._quick_capture_dialog

    def _on_quick_capture_requested(self, raw: str):
        result = self._submit_capture_text(str(raw or ""), default_bucket=self._capture_default_bucket("capture_dialog"))
        dlg = self._ensure_quick_capture_dialog()
        if result.success:
            dlg.capture_succeeded(result.message or "Captured.")
        else:
            dlg.capture_failed(result.message or "Capture failed.")

    def _open_quick_capture_dialog(self):
        dlg = self._ensure_quick_capture_dialog()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.input.setFocus()
        dlg.input.selectAll()

    def _install_optional_global_capture_hotkey(self):
        self._global_capture_hotkey = None
        try:
            from qhotkey import QHotkey  # type: ignore
        except Exception:
            return
        try:
            hotkey = QHotkey(shortcut_sequence("Ctrl+Alt+Space"), True, self)
            hotkey.activated.connect(self._open_quick_capture_dialog)
            self._global_capture_hotkey = hotkey
        except Exception:
            self._global_capture_hotkey = None

    def _init_quick_capture_tools(self):
        self._ensure_quick_capture_dialog()
        self._install_optional_global_capture_hotkey()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(self)
        tray.setToolTip(APP_NAME)
        tray.setIcon(self.windowIcon())
        menu = QMenu(self)

        quick_capture_act = QAction("Quick capture…", self)
        quick_capture_act.triggered.connect(self._open_quick_capture_dialog)
        show_app_act = QAction("Show app", self)
        show_app_act.triggered.connect(self._show_main_window)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)

        menu.addAction(quick_capture_act)
        menu.addAction(show_app_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._show_main_window()
            if reason in {
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick,
            }
            else None
        )
        tray.show()
        self._tray_icon = tray

    # ---------- Menus / toolbar ----------
    def _build_menus_and_toolbar(self):
        undo_act = QAction("Undo", self)
        undo_act.setShortcut(QKeySequence.StandardKey.Undo)
        undo_act.triggered.connect(self.undo_stack.undo)

        redo_act = QAction("Redo", self)
        redo_act.setShortcut(QKeySequence.StandardKey.Redo)
        redo_act.triggered.connect(self.undo_stack.redo)

        add_act = QAction("Add task", self)
        add_act.setShortcut(shortcut_sequence("Ctrl+N"))
        add_act.triggered.connect(self._add_task_and_edit)

        quick_capture_act = QAction("Quick capture…", self)
        quick_capture_act.setShortcut(shortcut_sequence("Ctrl+Alt+Space"))
        quick_capture_act.triggered.connect(self._open_quick_capture_dialog)

        add_child_act = QAction("Add child task", self)
        add_child_act.setShortcut(shortcut_sequence("Ctrl+Shift+N"))
        add_child_act.triggered.connect(self._add_child_to_selected)

        archive_act = QAction("Archive task", self)
        archive_act.setShortcut(QKeySequence.StandardKey.Delete)
        archive_act.triggered.connect(self._archive_selected)

        hard_del_act = QAction("Delete permanently", self)
        hard_del_act.setShortcut(QKeySequence(Qt.SHIFT | Qt.Key.Key_Delete))
        hard_del_act.triggered.connect(self._delete_selected_permanently)

        restore_act = QAction("Restore from archive", self)
        restore_act.triggered.connect(self._restore_selected)

        browse_archive_act = QAction("Browse archive…", self)
        browse_archive_act.setShortcut(shortcut_sequence("Ctrl+Shift+R"))
        browse_archive_act.triggered.connect(self._open_archive_browser)

        duplicate_act = QAction("Duplicate task", self)
        duplicate_act.setShortcut(shortcut_sequence("Ctrl+D"))
        duplicate_act.triggered.connect(self._duplicate_selected)

        duplicate_tree_act = QAction("Duplicate with children", self)
        duplicate_tree_act.setShortcut(shortcut_sequence("Ctrl+Shift+D"))
        duplicate_tree_act.triggered.connect(self._duplicate_selected_subtree)

        bulk_edit_act = QAction("Bulk edit…", self)
        bulk_edit_act.setShortcut(shortcut_sequence("Ctrl+Shift+B"))
        bulk_edit_act.triggered.connect(self._bulk_edit_selected)

        settings_act = QAction("Settings & Themes…", self)
        settings_act.triggered.connect(self._open_settings)

        toggle_controls_act = QAction("Capture/navigation panel", self)
        toggle_controls_act.setCheckable(True)
        toggle_controls_act.setChecked(True)
        toggle_controls_act.setShortcut(shortcut_sequence("Ctrl+Alt+C"))
        toggle_controls_act.triggered.connect(lambda checked: self.controls_dock.setVisible(bool(checked)))

        toggle_filters_act = QAction("Filters panel", self)
        toggle_filters_act.setCheckable(True)
        toggle_filters_act.setChecked(False)
        toggle_filters_act.setShortcut(shortcut_sequence("Ctrl+Alt+3"))
        toggle_filters_act.triggered.connect(self._toggle_filters_dock)

        toggle_table_act = QAction("Task table", self)
        toggle_table_act.setCheckable(True)
        toggle_table_act.setChecked(True)
        toggle_table_act.setShortcut(shortcut_sequence("Ctrl+Alt+1"))
        toggle_table_act.triggered.connect(self._set_tree_visible)

        float_table_act = QAction("Float task table", self)
        float_table_act.setCheckable(True)
        float_table_act.setChecked(False)
        float_table_act.triggered.connect(self._set_task_table_floating)

        toggle_details_act = QAction("Details panel", self)
        toggle_details_act.setCheckable(True)
        toggle_details_act.setChecked(True)
        toggle_details_act.setShortcut(shortcut_sequence("Ctrl+Alt+2"))
        toggle_details_act.triggered.connect(lambda checked: self.details_dock.setVisible(bool(checked)))

        toggle_project_act = QAction("Project cockpit", self)
        toggle_project_act.setCheckable(True)
        toggle_project_act.setChecked(False)
        toggle_project_act.setShortcuts(
            [
                shortcut_sequence("Ctrl+Alt+4"),
                shortcut_sequence("Ctrl+Shift+J"),
            ]
        )
        toggle_project_act.triggered.connect(lambda checked: self.project_dock.setVisible(bool(checked)))

        toggle_relationships_act = QAction("Relationship inspector", self)
        toggle_relationships_act.setCheckable(True)
        toggle_relationships_act.setChecked(False)
        toggle_relationships_act.setShortcut(shortcut_sequence("Ctrl+Alt+5"))
        toggle_relationships_act.triggered.connect(lambda checked: self.relationships_dock.setVisible(bool(checked)))

        toggle_undo_history_act = QAction("Undo history", self)
        toggle_undo_history_act.setCheckable(True)
        toggle_undo_history_act.setChecked(False)
        toggle_undo_history_act.setShortcut(shortcut_sequence("Ctrl+Alt+0"))
        toggle_undo_history_act.triggered.connect(lambda checked: self.undo_dock.setVisible(bool(checked)))

        toggle_focus_act = QAction("Focus mode", self)
        toggle_focus_act.setCheckable(True)
        toggle_focus_act.setChecked(False)
        toggle_focus_act.setShortcuts(
            [
                shortcut_sequence("Ctrl+Alt+6"),
                shortcut_sequence("Ctrl+Shift+F"),
            ]
        )
        toggle_focus_act.triggered.connect(lambda checked: self.focus_dock.setVisible(bool(checked)))

        toggle_calendar_act = QAction("Calendar/agenda", self)
        toggle_calendar_act.setCheckable(True)
        toggle_calendar_act.setChecked(False)
        toggle_calendar_act.setShortcut(shortcut_sequence("Ctrl+Alt+8"))
        toggle_calendar_act.triggered.connect(lambda checked: self.calendar_dock.setVisible(bool(checked)))

        toggle_review_act = QAction("Review workflow", self)
        toggle_review_act.setCheckable(True)
        toggle_review_act.setChecked(False)
        toggle_review_act.setShortcut(shortcut_sequence("Ctrl+Alt+7"))
        toggle_review_act.triggered.connect(lambda checked: self.review_dock.setVisible(bool(checked)))

        toggle_analytics_act = QAction("Analytics", self)
        toggle_analytics_act.setCheckable(True)
        toggle_analytics_act.setChecked(False)
        toggle_analytics_act.setShortcut(shortcut_sequence("Ctrl+Alt+9"))
        toggle_analytics_act.triggered.connect(lambda checked: self.analytics_dock.setVisible(bool(checked)))

        focus_workspace_act = QAction("Focus task workspace", self)
        focus_workspace_act.setShortcut(shortcut_sequence("Ctrl+1"))
        focus_workspace_act.triggered.connect(self._focus_task_workspace)

        focus_details_act = QAction("Focus details panel", self)
        focus_details_act.setShortcut(shortcut_sequence("Ctrl+2"))
        focus_details_act.triggered.connect(self._focus_details_panel)

        focus_filters_act = QAction("Focus filters panel", self)
        focus_filters_act.setShortcut(shortcut_sequence("Ctrl+3"))
        focus_filters_act.triggered.connect(self._focus_filters_panel)

        focus_project_act = QAction("Focus project cockpit", self)
        focus_project_act.setShortcut(shortcut_sequence("Ctrl+4"))
        focus_project_act.triggered.connect(self._focus_project_panel)

        focus_relationships_act = QAction("Focus relationship inspector", self)
        focus_relationships_act.setShortcut(shortcut_sequence("Ctrl+5"))
        focus_relationships_act.triggered.connect(self._focus_relationships_panel)

        focus_focus_mode_act = QAction("Focus focus mode", self)
        focus_focus_mode_act.setShortcut(shortcut_sequence("Ctrl+6"))
        focus_focus_mode_act.triggered.connect(self._focus_focus_panel)

        focus_review_act = QAction("Focus review workflow", self)
        focus_review_act.setShortcut(shortcut_sequence("Ctrl+7"))
        focus_review_act.triggered.connect(self._focus_review_panel)

        focus_calendar_act = QAction("Focus calendar / agenda", self)
        focus_calendar_act.setShortcut(shortcut_sequence("Ctrl+8"))
        focus_calendar_act.triggered.connect(self._focus_calendar_panel)

        focus_analytics_act = QAction("Focus analytics", self)
        focus_analytics_act.setShortcut(shortcut_sequence("Ctrl+9"))
        focus_analytics_act.triggered.connect(self._focus_analytics_panel)

        focus_undo_history_act = QAction("Focus undo history", self)
        focus_undo_history_act.setShortcut(shortcut_sequence("Ctrl+0"))
        focus_undo_history_act.triggered.connect(self._focus_undo_history_panel)

        collapse_all_act = QAction("Collapse all", self)
        collapse_all_act.setShortcut(shortcut_sequence("Ctrl+Alt+Up"))
        collapse_all_act.triggered.connect(self._collapse_all)

        expand_all_act = QAction("Expand all", self)
        expand_all_act.setShortcut(shortcut_sequence("Ctrl+Alt+Down"))
        expand_all_act.triggered.connect(self._expand_all)

        move_up_act = QAction("Move task up", self)
        move_up_act.setShortcut(shortcut_sequence("Ctrl+Shift+Up"))
        move_up_act.triggered.connect(lambda: self._move_selected_relative(-1))

        move_down_act = QAction("Move task down", self)
        move_down_act.setShortcut(shortcut_sequence("Ctrl+Shift+Down"))
        move_down_act.triggered.connect(lambda: self._move_selected_relative(1))

        # Keyboard-first workflow shortcuts.
        edit_current_act = QAction("Edit current", self)
        edit_current_act.setShortcut(QKeySequence(Qt.Key.Key_Return))
        edit_current_act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        edit_current_act.triggered.connect(self._edit_current_cell)

        edit_current_numpad_act = QAction("Edit current (numpad)", self)
        edit_current_numpad_act.setShortcut(QKeySequence(Qt.Key.Key_Enter))
        edit_current_numpad_act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        edit_current_numpad_act.triggered.connect(self._edit_current_cell)

        toggle_expand_act = QAction("Toggle expand/collapse", self)
        toggle_expand_act.setShortcut(QKeySequence(Qt.Key.Key_Space))
        toggle_expand_act.triggered.connect(self._toggle_current_collapse)

        save_view_act = QAction("Save current filter view…", self)
        save_view_act.triggered.connect(self._save_filter_view_prompt)
        load_view_act = QAction("Load saved filter view…", self)
        load_view_act.triggered.connect(self._load_filter_view_prompt)
        update_view_act = QAction("Update saved filter view…", self)
        update_view_act.triggered.connect(self._update_filter_view_prompt)
        delete_view_act = QAction("Delete saved filter view…", self)
        delete_view_act.triggered.connect(self._delete_filter_view_prompt)

        save_template_act = QAction("Save selected as template…", self)
        save_template_act.triggered.connect(self._save_template_prompt)
        create_template_act = QAction("Create from template…", self)
        create_template_act.triggered.connect(self._create_from_template_prompt)
        delete_template_act = QAction("Delete template…", self)
        delete_template_act.triggered.connect(self._delete_template_prompt)

        help_act = QAction("User Guide…", self)
        help_act.setShortcut(QKeySequence(Qt.Key.Key_F1))
        help_act.triggered.connect(self._open_help_dialog)

        about_act = QAction(f"About {APP_NAME}…", self)
        about_act.triggered.connect(self._open_about_dialog)

        onboarding_act = QAction("Quick Start…", self)
        onboarding_act.triggered.connect(self._open_onboarding_dialog)

        help_quick_add_act = QAction("Quick-add syntax", self)
        help_quick_add_act.triggered.connect(lambda: self._open_help_anchor("quick-add"))

        help_search_act = QAction("Search syntax", self)
        help_search_act.triggered.connect(lambda: self._open_help_anchor("search"))

        help_palette_act = QAction("Command palette help", self)
        help_palette_act.triggered.connect(lambda: self._open_help_anchor("command-palette"))

        help_templates_act = QAction("Template placeholders", self)
        help_templates_act.triggered.connect(lambda: self._open_help_anchor("templates"))

        help_shortcuts_act = QAction("Keyboard shortcuts", self)
        help_shortcuts_act.triggered.connect(lambda: self._open_help_anchor("shortcuts"))

        diagnostics_act = QAction("Diagnostics…", self)
        diagnostics_act.setShortcut(shortcut_sequence("Ctrl+Alt+D"))
        diagnostics_act.triggered.connect(self._open_diagnostics_dialog)

        log_viewer_act = QAction("Application log…", self)
        log_viewer_act.setShortcut(shortcut_sequence("Ctrl+Alt+L"))
        log_viewer_act.triggered.connect(self._open_log_viewer_dialog)

        snapshot_history_act = QAction("Snapshot history…", self)
        snapshot_history_act.setShortcut(shortcut_sequence("Ctrl+Alt+H"))
        snapshot_history_act.triggered.connect(self._open_snapshot_history_dialog)

        workspace_profiles_act = QAction("Workspace profiles…", self)
        workspace_profiles_act.setShortcut(shortcut_sequence("Ctrl+Alt+W"))
        workspace_profiles_act.triggered.connect(self._open_workspace_manager)

        command_palette_act = QAction("Command palette…", self)
        command_palette_act.setShortcut(shortcut_sequence("Ctrl+Shift+P"))
        command_palette_act.triggered.connect(self._open_command_palette)

        toggle_tooltips_act = QAction("Show tooltips", self)
        toggle_tooltips_act.setCheckable(True)
        toggle_tooltips_act.setChecked(True)
        toggle_tooltips_act.triggered.connect(self._set_tooltips_enabled)

        reminder_mode_group = QActionGroup(self)
        reminder_mode_group.setExclusive(True)

        reminder_mode_normal_act = QAction("Reminders on", self)
        reminder_mode_normal_act.setCheckable(True)
        reminder_mode_normal_act.triggered.connect(
            lambda checked=False: self._set_reminder_mode(self.REMINDER_MODE_NORMAL)
        )
        reminder_mode_group.addAction(reminder_mode_normal_act)

        reminder_mode_mute_act = QAction("Mute all reminders", self)
        reminder_mode_mute_act.setCheckable(True)
        reminder_mode_mute_act.triggered.connect(
            lambda checked=False: self._set_reminder_mode(self.REMINDER_MODE_MUTE_ALL)
        )
        reminder_mode_group.addAction(reminder_mode_mute_act)

        reminder_mode_p1_only_act = QAction("Only priority 1 reminders", self)
        reminder_mode_p1_only_act.setCheckable(True)
        reminder_mode_p1_only_act.triggered.connect(
            lambda checked=False: self._set_reminder_mode(self.REMINDER_MODE_PRIORITY1_ONLY)
        )
        reminder_mode_group.addAction(reminder_mode_p1_only_act)

        menubar = self.menuBar()

        m_file = menubar.addMenu("File")
        m_file.addAction(quick_capture_act)
        m_file.addAction(workspace_profiles_act)
        m_file.addAction(snapshot_history_act)
        m_file.addSeparator()
        m_file.addAction(settings_act)

        # Backup submenu (data + themes)
        m_backup = m_file.addMenu("Backup")

        export_db_act = QAction("Export Data…", self)
        export_db_act.triggered.connect(self._export_backup_data)
        m_backup.addAction(export_db_act)

        import_db_act = QAction("Import Data…", self)
        import_db_act.triggered.connect(self._import_backup_data)
        m_backup.addAction(import_db_act)

        m_backup.addSeparator()

        export_theme_act = QAction("Export Themes…", self)
        export_theme_act.triggered.connect(self._export_themes)
        m_backup.addAction(export_theme_act)

        import_theme_act = QAction("Import Themes…", self)
        import_theme_act.triggered.connect(self._import_themes)
        m_backup.addAction(import_theme_act)

        m_backup.addSeparator()
        backup_settings_act = QAction("Automatic backup settings…", self)
        backup_settings_act.triggered.connect(self._auto_backup_settings_prompt)
        m_backup.addAction(backup_settings_act)

        backup_now_act = QAction("Create snapshot now", self)
        backup_now_act.triggered.connect(self._create_backup_now)
        m_backup.addAction(backup_now_act)

        m_file.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        m_file.addAction(exit_act)

        m_edit = menubar.addMenu("Edit")
        m_edit.addAction(undo_act)
        m_edit.addAction(redo_act)
        m_edit.addSeparator()
        m_edit.addAction(add_act)
        m_edit.addAction(add_child_act)
        m_edit.addAction(archive_act)
        m_edit.addAction(hard_del_act)
        m_edit.addAction(restore_act)
        m_edit.addAction(browse_archive_act)
        m_edit.addSeparator()
        m_edit.addAction(duplicate_act)
        m_edit.addAction(duplicate_tree_act)
        m_edit.addAction(bulk_edit_act)
        m_edit.addSeparator()
        m_edit.addAction(move_up_act)
        m_edit.addAction(move_down_act)

        m_view = menubar.addMenu("View")
        m_view.addAction(toggle_controls_act)
        m_view.addAction(toggle_table_act)
        m_view.addAction(float_table_act)
        m_view.addAction(toggle_filters_act)
        m_view.addAction(toggle_details_act)
        m_view.addAction(toggle_project_act)
        m_view.addAction(toggle_relationships_act)
        m_view.addAction(toggle_undo_history_act)
        m_view.addAction(toggle_focus_act)
        m_view.addAction(toggle_calendar_act)
        m_view.addAction(toggle_review_act)
        m_view.addAction(toggle_analytics_act)
        m_view.addAction(log_viewer_act)
        m_view.addSeparator()

        m_focus = m_view.addMenu("Focus")
        m_focus.addAction(focus_workspace_act)
        m_focus.addAction(focus_details_act)
        m_focus.addAction(focus_filters_act)
        m_focus.addAction(focus_project_act)
        m_focus.addAction(focus_relationships_act)
        m_focus.addAction(focus_focus_mode_act)
        m_focus.addAction(focus_review_act)
        m_focus.addAction(focus_calendar_act)
        m_focus.addAction(focus_analytics_act)
        m_focus.addAction(focus_undo_history_act)
        m_view.addSeparator()

        m_saved_views = m_view.addMenu("Saved filter views")
        m_saved_views.addAction(save_view_act)
        m_saved_views.addAction(load_view_act)
        m_saved_views.addAction(update_view_act)
        m_saved_views.addAction(delete_view_act)

        m_perspective = m_view.addMenu("Perspective")
        for label, key in self._perspectives:
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, k=key: self._set_perspective_by_key(k))
            m_perspective.addAction(act)

        m_sort = m_view.addMenu("Sort mode")
        for label, key in self._sort_modes:
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, k=key: self._set_sort_mode_by_key(k))
            m_sort.addAction(act)

        m_view.addSeparator()
        m_view.addAction(collapse_all_act)
        m_view.addAction(expand_all_act)

        m_reminders = m_view.addMenu("Reminder Mode")
        m_reminders.addAction(reminder_mode_normal_act)
        m_reminders.addAction(reminder_mode_mute_act)
        m_reminders.addAction(reminder_mode_p1_only_act)

        m_tools = menubar.addMenu("Tools")
        m_tools.addAction(quick_capture_act)
        m_tools.addSeparator()
        m_tools.addAction(command_palette_act)
        m_tools.addSeparator()
        m_tools.addAction(workspace_profiles_act)
        m_tools.addAction(snapshot_history_act)
        m_tools.addSeparator()
        m_tools.addAction(toggle_relationships_act)
        m_tools.addAction(toggle_focus_act)
        m_tools.addAction(toggle_project_act)
        m_tools.addAction(onboarding_act)
        m_tools.addSeparator()
        m_tools.addAction(diagnostics_act)
        m_tools.addAction(log_viewer_act)
        m_tools.addSeparator()
        m_tools.addAction(save_template_act)
        m_tools.addAction(create_template_act)
        m_tools.addAction(delete_template_act)

        m_help = menubar.addMenu("Help")
        m_help.addAction(onboarding_act)
        m_help.addAction(help_act)
        m_help.addSeparator()
        m_help.addAction(help_quick_add_act)
        m_help.addAction(help_search_act)
        m_help.addAction(help_palette_act)
        m_help.addAction(help_templates_act)
        m_help.addAction(help_shortcuts_act)
        m_help.addAction(diagnostics_act)
        m_help.addAction(log_viewer_act)
        m_help.addAction(snapshot_history_act)
        m_help.addSeparator()
        m_help.addAction(about_act)
        m_help.addSeparator()
        m_help.addAction(toggle_tooltips_act)

        self.m_columns = menubar.addMenu("Columns")
        self.m_columns.aboutToShow.connect(self._rebuild_columns_menu)
        # macOS: empty menus sometimes don't show; build once now
        self._rebuild_columns_menu()

        tb = QToolBar("Main", self)
        tb.setObjectName("MainToolBar")
        self.addToolBar(tb)
        tb.addAction(add_act)
        tb.addAction(quick_capture_act)
        tb.addAction(add_child_act)
        tb.addAction(archive_act)
        tb.addAction(duplicate_act)
        tb.addAction(toggle_project_act)
        tb.addAction(toggle_relationships_act)
        tb.addAction(toggle_focus_act)
        tb.addSeparator()
        tb.addAction(undo_act)
        tb.addAction(redo_act)

        self._toggle_controls_act = toggle_controls_act
        self._toggle_filters_act = toggle_filters_act
        self._toggle_table_act = toggle_table_act
        self._float_table_act = float_table_act
        self._toggle_details_act = toggle_details_act
        self._toggle_project_act = toggle_project_act
        self._toggle_relationships_act = toggle_relationships_act
        self._toggle_undo_history_act = toggle_undo_history_act
        self._toggle_focus_act = toggle_focus_act
        self._toggle_calendar_act = toggle_calendar_act
        self._toggle_review_act = toggle_review_act
        self._toggle_analytics_act = toggle_analytics_act
        self._toggle_tooltips_act = toggle_tooltips_act
        self._focus_workspace_act = focus_workspace_act
        self._focus_details_act = focus_details_act
        self._focus_filters_act = focus_filters_act
        self._focus_project_act = focus_project_act
        self._focus_relationships_act = focus_relationships_act
        self._focus_focus_mode_act = focus_focus_mode_act
        self._focus_review_act = focus_review_act
        self._focus_calendar_act = focus_calendar_act
        self._focus_analytics_act = focus_analytics_act
        self._focus_undo_history_act = focus_undo_history_act

        add_shortcut_act = QAction(self)
        add_shortcut_act.setShortcut(QKeySequence("+"))
        add_shortcut_act.triggered.connect(self._add_task_and_edit)
        self.addAction(add_shortcut_act)

        remove_shortcut_act = QAction(self)
        remove_shortcut_act.setShortcut(QKeySequence("-"))
        remove_shortcut_act.triggered.connect(self._archive_selected)
        self.addAction(remove_shortcut_act)

        add_child_shortcut_act = QAction(self)
        add_child_shortcut_act.setShortcut(QKeySequence("Shift++"))
        add_child_shortcut_act.triggered.connect(self._add_child_to_selected)
        self.addAction(add_child_shortcut_act)

        remove_sibling_shortcut_act = QAction(self)
        remove_sibling_shortcut_act.setShortcut(QKeySequence("Shift+-"))
        remove_sibling_shortcut_act.triggered.connect(self._delete_sibling_of_selected)
        self.addAction(remove_sibling_shortcut_act)

        self.addAction(duplicate_act)
        self.addAction(duplicate_tree_act)
        self.addAction(quick_capture_act)
        self.addAction(move_up_act)
        self.addAction(move_down_act)
        self.addAction(command_palette_act)
        self.addAction(toggle_project_act)
        self.addAction(toggle_focus_act)
        self.addAction(toggle_relationships_act)
        self.addAction(onboarding_act)
        self.addAction(diagnostics_act)
        self.addAction(log_viewer_act)
        self.addAction(snapshot_history_act)
        self.addAction(workspace_profiles_act)
        self.addAction(browse_archive_act)
        self.addAction(focus_workspace_act)
        self.addAction(focus_details_act)
        self.addAction(focus_filters_act)
        self.addAction(focus_project_act)
        self.addAction(focus_relationships_act)
        self.addAction(focus_focus_mode_act)
        self.addAction(focus_review_act)
        self.addAction(focus_calendar_act)
        self.addAction(focus_analytics_act)
        self.addAction(focus_undo_history_act)
        self.view.addAction(edit_current_act)
        self.view.addAction(edit_current_numpad_act)
        self.addAction(toggle_expand_act)
        self.addAction(help_act)

        # Action help text for tooltips/status bar guidance.
        action_help: list[tuple[QAction, str]] = [
            (undo_act, "Undo the most recent change."),
            (redo_act, "Redo the next change in history."),
            (add_act, "Create a new top-level task."),
            (quick_capture_act, "Open the lightweight quick-capture window for fast inbox capture and command entry."),
            (add_child_act, "Create a child task under the selected row."),
            (archive_act, "Archive selected task(s)."),
            (hard_del_act, "Permanently delete selected task(s)."),
            (restore_act, "Restore selected archived task(s)."),
            (browse_archive_act, "Open archive browser and choose tasks to restore."),
            (duplicate_act, "Duplicate the selected task."),
            (duplicate_tree_act, "Duplicate selected task with all descendants."),
            (bulk_edit_act, "Apply one operation to multiple selected tasks."),
            (toggle_controls_act, "Show or hide the capture/navigation controls dock."),
            (toggle_table_act, "Show or hide the main task table while keeping the other panels active."),
            (float_table_act, "Detach the task table into its own window so it can live on another monitor."),
            (toggle_filters_act, "Show or hide the Filters dock."),
            (toggle_details_act, "Show or hide the Details dock."),
            (toggle_project_act, "Show or hide the project cockpit for charter, milestones, deliverables, timeline, and workload."),
            (toggle_relationships_act, "Show or hide the relationship inspector for dependencies, related tasks, and project context."),
            (toggle_undo_history_act, "Show or hide the Undo History dock."),
            (toggle_focus_act, "Show or hide the Focus mode dock for current actionable work."),
            (toggle_calendar_act, "Show or hide the Calendar/Agenda dock."),
            (toggle_review_act, "Show or hide the guided Review Workflow dock."),
            (toggle_analytics_act, "Show or hide analytics summary dashboard."),
            (focus_workspace_act, "Show the task workspace if needed and move keyboard focus into the task tree."),
            (focus_details_act, "Show the Details dock if needed and move keyboard focus into the details editor."),
            (focus_filters_act, "Show the Filters dock if needed and move keyboard focus into the filter controls."),
            (focus_project_act, "Show the project cockpit if needed and focus the current project workspace."),
            (focus_relationships_act, "Show the relationship inspector if needed and focus its current related-items list."),
            (focus_focus_mode_act, "Show Focus mode if needed and focus the current focus list."),
            (focus_review_act, "Show the Review Workflow dock if needed and focus the current review category list."),
            (focus_calendar_act, "Show the Calendar / Agenda dock if needed and focus the calendar view."),
            (focus_analytics_act, "Show the Analytics dock if needed and focus its trend list."),
            (focus_undo_history_act, "Show the Undo History dock if needed and focus the undo list."),
            (collapse_all_act, "Collapse every branch in the task tree."),
            (expand_all_act, "Expand every branch in the task tree."),
            (move_up_act, "Move selected task one row up among siblings."),
            (move_down_act, "Move selected task one row down among siblings."),
            (edit_current_act, "Edit the currently focused tree cell."),
            (toggle_expand_act, "Toggle expand/collapse for focused row."),
            (save_view_act, "Save current search/filter/sort/view state."),
            (load_view_act, "Load a saved filter view."),
            (update_view_act, "Update an existing saved filter view with current state."),
            (delete_view_act, "Delete a saved filter view."),
            (save_template_act, "Save selected task subtree as a reusable template."),
            (create_template_act, "Create tasks from a saved template."),
            (delete_template_act, "Delete a saved template."),
            (settings_act, "Open app settings and theme editor."),
            (workspace_profiles_act, "Manage named workspace profiles and switch databases explicitly."),
            (backup_settings_act, "Configure automatic backup interval and retention."),
            (backup_now_act, "Create a versioned backup snapshot now."),
            (snapshot_history_act, "Browse local restore points and restore them into a new database copy or workspace."),
            (command_palette_act, "Open the searchable command palette for keyboard-first actions."),
            (onboarding_act, "Open the quick-start guide and onboarding tips."),
            (help_act, "Open the embedded help guide with indexed chapters."),
            (help_quick_add_act, "Jump straight to quick-add syntax help."),
            (help_search_act, "Jump straight to search syntax help."),
            (help_palette_act, "Jump straight to command palette help."),
            (help_templates_act, "Jump straight to template placeholder help."),
            (help_shortcuts_act, "Jump straight to keyboard shortcuts help."),
            (about_act, f"Show version and product information for {APP_NAME}."),
            (diagnostics_act, "Inspect database health, restore-point availability, and repair options."),
            (log_viewer_act, "Open the application log viewer for crash entries and operation history."),
            (toggle_tooltips_act, "Turn interface tooltips on or off."),
            (reminder_mode_normal_act, "Show all due reminders."),
            (reminder_mode_mute_act, "Suppress all reminder popups."),
            (reminder_mode_p1_only_act, "Only show reminders for priority 1 tasks."),
            (exit_act, "Close the application."),
        ]
        for act, txt in action_help:
            self._set_action_help(act, txt)

        self._reminder_mode_normal_act = reminder_mode_normal_act
        self._reminder_mode_mute_act = reminder_mode_mute_act
        self._reminder_mode_p1_only_act = reminder_mode_p1_only_act
        self._set_reminder_mode(self._reminder_mode, show_message=False)

    def _toggle_filters_dock(self, checked: bool):
        if checked:
            self.filter_dock.show()
        else:
            self.filter_dock.hide()
        self._schedule_row_action_button_update()

    def _set_reminder_mode(self, mode: str, show_message: bool = True):
        m = str(mode or "").strip().lower()
        if m not in {self.REMINDER_MODE_NORMAL, self.REMINDER_MODE_MUTE_ALL, self.REMINDER_MODE_PRIORITY1_ONLY}:
            m = self.REMINDER_MODE_NORMAL
        self._reminder_mode = m
        if hasattr(self, "_reminder_mode_normal_act"):
            self._reminder_mode_normal_act.setChecked(m == self.REMINDER_MODE_NORMAL)
        if hasattr(self, "_reminder_mode_mute_act"):
            self._reminder_mode_mute_act.setChecked(m == self.REMINDER_MODE_MUTE_ALL)
        if hasattr(self, "_reminder_mode_p1_only_act"):
            self._reminder_mode_p1_only_act.setChecked(m == self.REMINDER_MODE_PRIORITY1_ONLY)
        self.model.settings.setValue("ui/reminder_mode", m)
        if show_message:
            label = {
                self.REMINDER_MODE_NORMAL: "Reminders enabled",
                self.REMINDER_MODE_MUTE_ALL: "Reminders muted",
                self.REMINDER_MODE_PRIORITY1_ONLY: "Only priority-1 reminders enabled",
            }.get(m, "Reminder mode updated")
            self.statusBar().showMessage(label, 2500)

    def _rebuild_columns_menu(self):
        self.m_columns.clear()

        # Always include manage actions so menu is never empty
        add_col_act = QAction("Add custom column…", self)
        add_col_act.triggered.connect(self._add_custom_column)

        rem_col_act = QAction("Remove custom column…", self)
        rem_col_act.triggered.connect(self._remove_custom_column)

        self.m_columns.addAction(add_col_act)
        self.m_columns.addAction(rem_col_act)
        self.m_columns.addSeparator()

        for logical in range(self.proxy.columnCount()):
            key = self.model.column_key(logical)
            title = self.proxy.headerData(logical, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)

            act = QAction(str(title), self)
            act.setCheckable(True)
            act.setChecked(not self.view.isColumnHidden(logical))

            def make_toggle(col_index: int, col_key: str):
                def _toggle(checked: bool):
                    self.view.setColumnHidden(col_index, not checked)
                    self.model.settings.setValue(f"columns/hidden/{col_key}", not checked)
                    self._schedule_row_action_button_update()
                return _toggle

            act.triggered.connect(make_toggle(logical, key))
            self.m_columns.addAction(act)

    # ---------- Expand / collapse all ----------
    def _collapse_all(self):
        self.view.collapseAll()
        for node in self.model.iter_nodes_preorder():
            if node.task:
                self.model.set_collapsed(int(node.task["id"]), True)
        self._schedule_row_action_button_update()

    def _expand_all(self):
        self.view.expandAll()
        for node in self.model.iter_nodes_preorder():
            if node.task:
                self.model.set_collapsed(int(node.task["id"]), False)
        self._schedule_row_action_button_update()

    # ---------- Context menu + selection helpers ----------
    def _create_or_edit_category_folder(
        self,
        folder_id: int | None = None,
        *,
        parent_folder_id: int | None = None,
    ) -> int | None:
        folder = None
        if folder_id is not None:
            for row in self.model.list_category_folders():
                if int(row.get("id") or 0) == int(folder_id):
                    folder = row
                    break
        dlg = CategoryFolderDialog(folder, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return None
        payload = dlg.payload()
        if not str(payload.get("name") or "").strip():
            QMessageBox.warning(self, "Category folder", "Category name is required.")
            return None
        try:
            if folder_id is None:
                return self.model.create_category_folder(
                    str(payload.get("name") or ""),
                    parent_folder_id,
                    color_hex=payload.get("color_hex"),
                    icon_name=payload.get("icon_name"),
                    identifier=payload.get("identifier"),
                )
            self.model.update_category_folder(int(folder_id), payload)
            return int(folder_id)
        except Exception as e:
            QMessageBox.warning(self, "Category folder", str(e))
            return None

    def _prompt_new_category(self, parent_folder_id: int | None = None):
        new_folder_id = self._create_or_edit_category_folder(
            None,
            parent_folder_id=parent_folder_id,
        )
        if new_folder_id is not None:
            self.statusBar().showMessage("Category folder created.", 2500)

    def _customize_category_folder(self, folder_id: int):
        updated_id = self._create_or_edit_category_folder(int(folder_id))
        if updated_id is not None:
            self.statusBar().showMessage("Category folder updated.", 2500)

    def _delete_category_folder(self, folder_id: int):
        reply = QMessageBox.question(
            self,
            "Delete category folder",
            "Delete this category folder?\n\nThe folder must be empty before it can be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.model.delete_category_folder(int(folder_id))
        except Exception as e:
            QMessageBox.warning(self, "Delete category folder", str(e))
            return
        self.statusBar().showMessage("Category folder deleted.", 2500)

    def _assign_selected_tasks_to_category(self, folder_id: int | None):
        ids = self._selected_task_ids()
        if not ids:
            return
        failures: list[str] = []
        for task_id in ids:
            try:
                self.model.assign_task_to_category_folder(int(task_id), folder_id)
            except Exception as e:
                failures.append(str(e))
        if failures:
            QMessageBox.warning(self, "Move to category", failures[0])
            return
        self.statusBar().showMessage("Task category updated.", 2500)

    def _add_task_in_category(self, folder_id: int):
        created = self.model.add_task_with_values(
            "",
            None,
            None,
            parent_id=None,
            category_folder_id=int(folder_id),
        )
        if created and self.model.last_added_task_id() is not None:
            self._focus_task_by_id(int(self.model.last_added_task_id()))

    def _populate_category_assignment_menu(self, menu: QMenu):
        folders = self.model.list_category_folders()
        if not folders:
            act = menu.addAction("Create category…")
            act.triggered.connect(lambda: self._prompt_new_category(None))
            return
        clear_act = menu.addAction("No category")
        clear_act.triggered.connect(lambda: self._assign_selected_tasks_to_category(None))
        menu.addSeparator()
        for row in folders:
            label = str(row.get("path") or row.get("display_name") or row.get("name") or "Category")
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, folder_id=int(row.get("id")): self._assign_selected_tasks_to_category(folder_id)
            )

    def _open_context_menu(self, pos):
        index = self.view.indexAt(pos)
        menu = QMenu(self)
        if not index.isValid():
            add_category = QAction("Add category folder", self)
            add_category.triggered.connect(lambda: self._prompt_new_category(None))
            menu.addAction(add_category)
            menu.exec(self.view.viewport().mapToGlobal(pos))
            return

        self.view.setCurrentIndex(index)
        src = self.proxy.mapToSource(index)
        folder_id = self.model.folder_id_from_index(src)
        task_id = self.model.task_id_from_index(src)

        if folder_id is not None:
            add_task_act = QAction("Add task in category", self)
            add_task_act.triggered.connect(
                lambda: self._add_task_in_category(int(folder_id))
            )
            menu.addAction(add_task_act)

            add_subfolder_act = QAction("Add subcategory", self)
            add_subfolder_act.triggered.connect(
                lambda: self._prompt_new_category(int(folder_id))
            )
            menu.addAction(add_subfolder_act)

            menu.addSeparator()

            customize_act = QAction("Customize category…", self)
            customize_act.triggered.connect(
                lambda: self._customize_category_folder(int(folder_id))
            )
            menu.addAction(customize_act)

            delete_folder_act = QAction("Delete category", self)
            delete_folder_act.triggered.connect(
                lambda: self._delete_category_folder(int(folder_id))
            )
            menu.addAction(delete_folder_act)

            menu.exec(self.view.viewport().mapToGlobal(pos))
            return

        if task_id is None:
            return

        add_child = QAction("Add child task", self)
        add_child.triggered.connect(self._add_child_to_selected)
        menu.addAction(add_child)

        move_to_category = menu.addMenu("Move to category")
        self._populate_category_assignment_menu(move_to_category)

        duplicate = QAction("Duplicate", self)
        duplicate.triggered.connect(self._duplicate_selected)
        menu.addAction(duplicate)

        duplicate_sub = QAction("Duplicate with children", self)
        duplicate_sub.triggered.connect(self._duplicate_selected_subtree)
        menu.addAction(duplicate_sub)

        archive_act = QAction("Archive", self)
        archive_act.triggered.connect(self._archive_selected)
        menu.addAction(archive_act)

        restore_act = QAction("Restore", self)
        restore_act.triggered.connect(self._restore_selected)
        menu.addAction(restore_act)

        browse_archive_act = QAction("Browse archive…", self)
        browse_archive_act.triggered.connect(self._open_archive_browser)
        menu.addAction(browse_archive_act)

        menu.addSeparator()

        del_act = QAction("Delete permanently", self)
        del_act.triggered.connect(self._delete_selected_permanently)
        menu.addAction(del_act)

        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _selected_proxy_index(self):
        idx = self.view.currentIndex()
        return idx if idx.isValid() else None

    def _selected_task_id(self):
        pidx = self._selected_proxy_index()
        if not pidx:
            return None
        src = self.proxy.mapToSource(pidx)
        return self.model.task_id_from_index(src)

    def _selected_task_ids(self) -> list[int]:
        sel = self.view.selectionModel()
        if sel is None:
            tid = self._selected_task_id()
            return [tid] if tid is not None else []
        ids = []
        seen = set()
        for pidx in sel.selectedRows():
            src = self.proxy.mapToSource(pidx)
            tid = self.model.task_id_from_index(src)
            if tid is None or tid in seen:
                continue
            seen.add(tid)
            ids.append(int(tid))
        if not ids:
            tid = self._selected_task_id()
            if tid is not None:
                ids = [int(tid)]
        return ids

    def _neighbor_task_id_before_removal(self, removed_ids: list[int]) -> int | None:
        current = self._selected_proxy_index()
        if not current:
            return None
        removed = {int(x) for x in removed_ids if int(x) > 0}
        probe = current.siblingAtColumn(0)

        def _task_id_for_proxy_index(pidx: QModelIndex) -> int | None:
            if not pidx.isValid():
                return None
            src = self.proxy.mapToSource(pidx)
            tid = self.model.task_id_from_index(src)
            return int(tid) if tid is not None else None

        above = probe
        while True:
            above = self.view.indexAbove(above)
            if not above.isValid():
                break
            tid = _task_id_for_proxy_index(above)
            if tid is not None and tid not in removed:
                return tid

        below = probe
        while True:
            below = self.view.indexBelow(below)
            if not below.isValid():
                break
            tid = _task_id_for_proxy_index(below)
            if tid is not None and tid not in removed:
                return tid

        return None

    def _restore_focus_after_removal(self, task_id: int | None):
        if task_id is not None:
            self._focus_task_by_id(int(task_id))
            if self._selected_task_id() == int(task_id):
                return
        first = self.proxy.index(0, 0)
        if first.isValid():
            self.view.setCurrentIndex(first)
            self.view.scrollTo(first)

    def _archive_selected(self):
        ids = self._selected_task_ids()
        if not ids:
            return
        focus_task_id = self._neighbor_task_id_before_removal(ids)
        self.model.archive_tasks(ids)
        QTimer.singleShot(0, lambda tid=focus_task_id: self._restore_focus_after_removal(tid))
        self._refresh_details_dock()
        self._refresh_calendar_list()

    def _restore_selected(self):
        ids = self._selected_task_ids()
        archived_ids = [int(tid) for tid in ids if self.model.is_task_archived(int(tid))]
        if archived_ids:
            self._restore_from_archive_ids(archived_ids)
            return
        self._open_archive_browser()

    def _restore_from_archive_ids(self, ids: list[int]):
        task_ids = sorted({int(x) for x in ids if int(x) > 0})
        if not task_ids:
            return
        self.model.restore_tasks(task_ids)
        self._refresh_details_dock()
        self._refresh_calendar_list()
        self.statusBar().showMessage(f"Restored {len(task_ids)} archived task(s).", 3000)

    def _open_archive_browser(self):
        rows = self.model.fetch_archive_roots()
        if not rows:
            QMessageBox.information(self, "Archive is empty", "There are no archived tasks to restore.")
            return
        dlg = ArchiveBrowserDialog(rows, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        chosen = dlg.selected_task_ids()
        if not chosen:
            return
        self._restore_from_archive_ids(chosen)

    def _delete_selected_permanently(self):
        ids = self._selected_task_ids()
        if not ids:
            return
        res = QMessageBox.warning(
            self,
            "Delete permanently",
            "This will permanently delete the selected tasks and their subtrees.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        focus_task_id = self._neighbor_task_id_before_removal(ids)
        self.model.hard_delete_tasks(ids)
        QTimer.singleShot(0, lambda tid=focus_task_id: self._restore_focus_after_removal(tid))
        self._refresh_details_dock()
        self._refresh_calendar_list()

    def _add_child_to_selected(self):
        pidx = self._selected_proxy_index()
        if not pidx:
            self.model.add_task(parent_id=None)
            return

        src = self.proxy.mapToSource(pidx)
        task_id = self.model.task_id_from_index(src)
        if task_id is None:
            return

        self.view.expand(pidx)
        if not self.model.add_child_task(task_id):
            self._pending_edit_on_insert = False
            self._show_nesting_limit_message()

        self._schedule_row_action_button_update()

    def _on_current_changed(self, *_):
        if hasattr(self, "details_panel"):
            self.details_panel.flush_pending_save()
        if hasattr(self, "project_panel"):
            self.project_panel.flush_pending_saves()
        self._schedule_row_action_button_update()
        self._refresh_active_task_views()

    @staticmethod
    def _shift_iso_date(value: str | None, delta_days: int) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return (
                datetime.strptime(raw[:10], "%Y-%m-%d").date()
                + timedelta(days=int(delta_days))
            ).isoformat()
        except Exception:
            return raw or None

    def _project_panel_schedule_timeline_item(
        self,
        kind: str,
        item_id: int,
        start_date: str | None,
        end_date: str | None,
    ):
        item_kind = str(kind or "").strip().lower()
        preserved_task_id = self._selected_task_id()
        try:
            if item_kind == "task":
                self.model.undo_stack.beginMacro("Reschedule task from planner")
                try:
                    self.model.set_task_start_date(int(item_id), start_date)
                    self.model.set_task_due_date(int(item_id), end_date)
                finally:
                    self.model.undo_stack.endMacro()
            elif item_kind == "milestone":
                self.model.set_milestone_dates(int(item_id), start_date, end_date)
            elif item_kind == "deliverable":
                self.model.set_deliverable_due_date(int(item_id), end_date)
            else:
                return
            log_event(
                "Timeline schedule updated",
                context="project.timeline.schedule",
                db_path=self.db.path,
                details={
                    "kind": item_kind,
                    "item_id": int(item_id),
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        except Exception as e:
            log_exception(e, context="project-timeline-schedule", db_path=self.db.path)
            QMessageBox.warning(self, "Timeline schedule failed", str(e))
            return
        self._refresh_project_panel()
        self._refresh_details_dock()
        self._refresh_calendar_list()
        self._refresh_review_panel()
        self._refresh_focus_panel()
        self._refresh_relationships_panel()
        self._restore_task_focus_if_needed(preserved_task_id)

    def _move_selected_task_from_timeline(self, task_id: int, delta: int):
        tid = int(task_id or 0)
        if tid <= 0:
            return
        if self.model.move_task_relative(tid, int(delta)):
            log_event(
                "Timeline row moved",
                context="project.timeline.reorder",
                db_path=self.db.path,
                details={"task_id": tid, "mode": "relative", "delta": int(delta)},
            )
            self._focus_task_by_id(tid)

    def _move_task_to_row_from_timeline(self, task_id: int, parent_id, row: int):
        tid = int(task_id or 0)
        if tid <= 0:
            return
        target_parent = None if parent_id is None else int(parent_id)
        if self.model.move_task_to_row(tid, target_parent, int(row)):
            log_event(
                "Timeline row moved",
                context="project.timeline.reorder",
                db_path=self.db.path,
                details={
                    "task_id": tid,
                    "mode": "absolute",
                    "parent_id": target_parent,
                    "row": int(row),
                },
            )
            self._focus_task_by_id(tid)

    def _project_panel_edit_task_dependencies(self, task_id: int, dependency_ids: list):
        try:
            self.model.set_task_dependencies(int(task_id), [int(x) for x in dependency_ids or []])
            log_event(
                "Timeline dependencies updated",
                context="project.timeline.dependencies",
                db_path=self.db.path,
                details={
                    "kind": "task",
                    "task_id": int(task_id),
                    "dependency_count": len(list(dependency_ids or [])),
                },
            )
        except Exception as e:
            log_exception(e, context="project-timeline-task-dependencies", db_path=self.db.path)
            QMessageBox.warning(self, "Dependency update failed", str(e))
            return
        self._refresh_project_panel()

    def _project_panel_edit_milestone_dependencies(self, milestone_id: int, dependency_refs: list):
        try:
            self.model.set_milestone_dependencies(int(milestone_id), list(dependency_refs or []))
            log_event(
                "Timeline dependencies updated",
                context="project.timeline.dependencies",
                db_path=self.db.path,
                details={
                    "kind": "milestone",
                    "milestone_id": int(milestone_id),
                    "dependency_count": len(list(dependency_refs or [])),
                },
            )
        except Exception as e:
            log_exception(e, context="project-timeline-milestone-dependencies", db_path=self.db.path)
            QMessageBox.warning(self, "Dependency update failed", str(e))
            return
        self._refresh_project_panel()

    def _set_perspective_by_key(self, key: str):
        for i in range(self.view_mode.count()):
            if self.view_mode.itemData(i) == key:
                self.view_mode.setCurrentIndex(i)
                self._sync_perspective_buttons(key)
                return
        self.view_mode.setCurrentIndex(0)
        self._sync_perspective_buttons("all")

    def _on_perspective_changed(self, *_):
        key = str(self.view_mode.currentData() or "all")
        self.proxy.set_perspective(key)
        self._sync_perspective_buttons(key)
        self.model.settings.setValue("ui/perspective", key)
        self._update_dragdrop_mode()
        self._refresh_task_browser()
        self._refresh_calendar_list()
        self._schedule_row_action_button_update()

    def _sync_perspective_buttons(self, active_key: str):
        buttons = getattr(self, "_perspective_buttons", {})
        for key, btn in buttons.items():
            was_blocked = btn.blockSignals(True)
            btn.setChecked(str(key) == str(active_key))
            btn.blockSignals(was_blocked)

    def _set_sort_mode_by_key(self, key: str):
        for i in range(self.sort_mode.count()):
            if self.sort_mode.itemData(i) == key:
                self.sort_mode.setCurrentIndex(i)
                return
        self.sort_mode.setCurrentIndex(0)

    def _on_sort_mode_changed(self, *_):
        key = str(self.sort_mode.currentData() or "manual")
        self.proxy.set_sort_mode(key)
        self.model.settings.setValue("ui/sort_mode", key)
        self._update_dragdrop_mode()
        self._refresh_task_browser()
        self._schedule_row_action_button_update()

    def _source_index_for_task_id(self, task_id: int, column: int = 0):
        node = self.model.node_for_id(int(task_id))
        if not node:
            return QModelIndex()
        return self.model._index_for_node(node, int(column))

    def _column_index_for_key(self, key: str) -> int | None:
        target = str(key or "").strip()
        if not target:
            return None
        for logical in range(self.model.columnCount()):
            if self.model.column_key(logical) == target:
                return logical
        return None

    def _default_unfiltered_state(self) -> dict:
        return {
            "search_text": "",
            "filter_panel": {
                "statuses": [],
                "priority_min": 1,
                "priority_max": 5,
                "due_enabled": False,
                "due_from": None,
                "due_to": None,
                "hide_done": False,
                "overdue_only": False,
                "blocked_only": False,
                "waiting_only": False,
                "show_children_of_matches": True,
                "tags": [],
            },
            "perspective": "all",
            "sort_mode": str(self.sort_mode.currentData() or "manual"),
        }

    def _proxy_index_for_task_id(
        self,
        task_id: int,
        *,
        reveal_if_needed: bool = False,
    ) -> QModelIndex:
        src = self._source_index_for_task_id(int(task_id), 0)
        if not src.isValid():
            return QModelIndex()
        pidx = self.proxy.mapFromSource(src)
        if pidx.isValid() or not reveal_if_needed:
            return pidx
        self._apply_filter_state(self._default_unfiltered_state())
        pidx = self.proxy.mapFromSource(src)
        if pidx.isValid():
            self.statusBar().showMessage(
                "Adjusted the main view to reveal the selected task.",
                3000,
            )
        return pidx

    def _focus_task_by_id(self, task_id: int):
        pidx = self._proxy_index_for_task_id(
            int(task_id),
            reveal_if_needed=True,
        )
        if not pidx.isValid():
            return
        already_current = (
            self._selected_task_id() is not None
            and int(self._selected_task_id()) == int(task_id)
        )
        self._expand_proxy_ancestors(pidx)
        self.view.setCurrentIndex(pidx)
        self.view.scrollTo(pidx)
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        if already_current:
            self._refresh_active_task_views()

    def _edit_current_cell(self):
        if self.view.state() == QAbstractItemView.State.EditingState:
            return
        idx = self.view.currentIndex()
        if idx.isValid():
            self.view.edit(idx)

    def _toggle_current_collapse(self):
        idx = self.view.currentIndex()
        if not idx.isValid():
            return
        if self.view.isExpanded(idx):
            self.view.collapse(idx)
        else:
            self.view.expand(idx)

    def _move_selected_relative(self, delta: int):
        tid = self._selected_task_id()
        if tid is None:
            return
        if self.model.move_task_relative(int(tid), int(delta)):
            self._focus_task_by_id(int(tid))
            self._schedule_row_action_button_update()

    def _duplicate_selected(self):
        tid = self._selected_task_id()
        if tid is None:
            return
        new_id = self.model.duplicate_task(int(tid), include_children=False)
        if new_id:
            self._focus_task_by_id(int(new_id))
            self._refresh_calendar_list()

    def _duplicate_selected_subtree(self):
        tid = self._selected_task_id()
        if tid is None:
            return
        new_id = self.model.duplicate_task(int(tid), include_children=True)
        if new_id:
            self._focus_task_by_id(int(new_id))
            self._refresh_calendar_list()

    def _bulk_edit_selected(self):
        ids = self._selected_task_ids()
        if not ids:
            return
        op, ok = QInputDialog.getItem(
            self,
            "Bulk edit",
            "Operation",
            [
                "Set status",
                "Set priority",
                "Shift due date (days)",
                "Set due date",
                "Add tags",
                "Remove tags",
                "Archive",
                "Delete permanently",
            ],
            0,
            False,
        )
        if not ok or not op:
            return

        if op == "Set status":
            status, ok = QInputDialog.getItem(self, "Bulk status", "Status", STATUSES, 0, False)
            if not ok:
                return
            status_col = self._column_index_for_key("status")
            if status_col is None:
                return
            self.model.undo_stack.beginMacro("Bulk set status")
            try:
                for tid in ids:
                    src = self._source_index_for_task_id(int(tid), status_col)
                    if src.isValid():
                        self.model.setData(src, status, Qt.ItemDataRole.EditRole)
            finally:
                self.model.undo_stack.endMacro()
            return

        if op == "Set priority":
            value, ok = QInputDialog.getInt(self, "Bulk priority", "Priority (1-5)", 3, 1, 5, 1)
            if not ok:
                return
            priority_col = self._column_index_for_key("priority")
            if priority_col is None:
                return
            self.model.undo_stack.beginMacro("Bulk set priority")
            try:
                for tid in ids:
                    src = self._source_index_for_task_id(int(tid), priority_col)
                    if src.isValid():
                        self.model.setData(src, int(value), Qt.ItemDataRole.EditRole)
            finally:
                self.model.undo_stack.endMacro()
            return

        if op == "Shift due date (days)":
            delta, ok = QInputDialog.getInt(self, "Shift due date", "Days (+/-)", 1, -3650, 3650, 1)
            if not ok:
                return
            self.model.undo_stack.beginMacro("Bulk shift due date")
            try:
                for tid in ids:
                    node = self.model.node_for_id(int(tid))
                    if not node or not node.task:
                        continue
                    due = str(node.task.get("due_date") or "").strip()
                    if not due:
                        continue
                    try:
                        d = datetime.strptime(due[:10], "%Y-%m-%d").date() + timedelta(days=int(delta))
                    except Exception:
                        continue
                    src = self._source_index_for_task_id(int(tid), 1)
                    if src.isValid():
                        self.model.setData(src, d.isoformat(), Qt.ItemDataRole.EditRole)
            finally:
                self.model.undo_stack.endMacro()
            return

        if op == "Set due date":
            value, ok = QInputDialog.getText(self, "Set due date", "Due date (YYYY-MM-DD), leave blank to clear:")
            if not ok:
                return
            due_text = str(value or "").strip() or None
            self.model.undo_stack.beginMacro("Bulk set due date")
            try:
                for tid in ids:
                    src = self._source_index_for_task_id(int(tid), 1)
                    if src.isValid():
                        self.model.setData(src, due_text, Qt.ItemDataRole.EditRole)
            finally:
                self.model.undo_stack.endMacro()
            return

        if op == "Add tags":
            value, ok = QInputDialog.getText(self, "Add tags", "Tags to add (comma-separated):")
            if not ok:
                return
            tags_to_add = [x.strip() for x in str(value or "").split(",") if x.strip()]
            if not tags_to_add:
                return
            self.model.undo_stack.beginMacro("Bulk add tags")
            try:
                for tid in ids:
                    details = self.model.task_details(int(tid)) or {}
                    existing = list(details.get("tags") or [])
                    merged = existing[:]
                    lower = {x.lower() for x in existing}
                    for t in tags_to_add:
                        if t.lower() not in lower:
                            merged.append(t)
                    self.model.set_task_tags(int(tid), merged)
            finally:
                self.model.undo_stack.endMacro()
            return

        if op == "Remove tags":
            value, ok = QInputDialog.getText(self, "Remove tags", "Tags to remove (comma-separated):")
            if not ok:
                return
            tags_to_remove = {x.strip().lower() for x in str(value or "").split(",") if x.strip()}
            if not tags_to_remove:
                return
            self.model.undo_stack.beginMacro("Bulk remove tags")
            try:
                for tid in ids:
                    details = self.model.task_details(int(tid)) or {}
                    existing = list(details.get("tags") or [])
                    keep = [x for x in existing if x.lower() not in tags_to_remove]
                    self.model.set_task_tags(int(tid), keep)
            finally:
                self.model.undo_stack.endMacro()
            return

        if op == "Archive":
            self.model.archive_tasks(ids)
            self._refresh_calendar_list()
            self._refresh_details_dock()
            return

        if op == "Delete permanently":
            self._delete_selected_permanently()

    # ---------- Settings ----------
    def _apply_theme_now(self):
        self.model.apply_theme_to_app(QApplication.instance())
        icon = self.model.current_window_icon()
        if icon is not None:
            self.setWindowIcon(icon)
            if self._tray_icon is not None:
                self._tray_icon.setIcon(icon)
            if self._floating_table_window is not None:
                self._floating_table_window.setWindowIcon(icon)
        self.model.refresh_due_highlights()

    def _open_settings(self):
        dlg = SettingsDialog(self.model.settings, self)
        if dlg.exec():
            self._apply_theme_now()
            self._schedule_row_action_button_update()

    def _add_custom_column(self):
        dlg = AddColumnDialog(self)
        if dlg.exec():
            name, col_type, list_values = dlg.result_value()
            self.model.add_custom_column(name, col_type, list_values)

    def _remove_custom_column(self):
        cols = self.model.custom_columns_snapshot()
        if not cols:
            QMessageBox.information(self, "No custom columns", "There are no custom columns to remove.")
            return

        dlg = RemoveColumnDialog(cols, self)
        if dlg.exec():
            col_id = dlg.selected_column_id()
            if col_id is not None:
                self.model.remove_custom_column(col_id)

    # ---------- Collapse persistence ----------
    def _on_collapsed(self, proxy_index):
        if self._applying_expand_state:
            return
        src = self.proxy.mapToSource(proxy_index)
        task_id = self.model.task_id_from_index(src)
        if task_id is not None:
            self.model.set_collapsed(task_id, True)
        self._schedule_row_action_button_update()

    def _on_expanded(self, proxy_index):
        if self._applying_expand_state:
            return
        src = self.proxy.mapToSource(proxy_index)
        task_id = self.model.task_id_from_index(src)
        if task_id is not None:
            self.model.set_collapsed(task_id, False)
        self._schedule_row_action_button_update()

    def _apply_collapsed_state_to_view(self):
        self._applying_expand_state = True
        try:
            for node in self.model.iter_nodes_preorder():
                if not node.task:
                    continue

                src_idx = self._source_index_for_node(node)
                if not src_idx.isValid():
                    continue

                pidx = self.proxy.mapFromSource(src_idx)
                if not pidx.isValid():
                    continue

                collapsed = int(node.task.get("is_collapsed", 0)) == 1
                self.view.setExpanded(pidx, not collapsed)
        finally:
            self._applying_expand_state = False

        self._schedule_row_action_button_update()

    def _source_index_for_node(self, node):
        if node == self.model.root or node is None or node.task is None or node.parent is None:
            return QModelIndex()

        parent = node.parent
        pidx = self._source_index_for_node(parent)

        row = 0
        for i, ch in enumerate(parent.children):
            if ch is node:
                row = i
                break

        return self.model.index(row, 0, pidx)

    def _apply_default_column_widths(self):
        widths = {
            "description": 360,
            "due_date": 130,
            "reminder_at": 170,
            "last_update": 170,
            "priority": 80,
            "status": 120,
            "progress": 130,
            "project_health": 120,
            "next_action": 260,
            "project_state": 140,
        }
        for logical in range(self.proxy.columnCount()):
            key = self.model.column_key(logical)
            w = widths.get(key)
            if w is not None:
                self.view.setColumnWidth(logical, int(w))

    def _minimum_header_width_for_column(self, logical: int) -> int:
        header = self.view.header()
        title = str(
            self.proxy.headerData(
                logical,
                Qt.Orientation.Horizontal,
                Qt.ItemDataRole.DisplayRole,
            )
            or self.model.headerData(
                logical,
                Qt.Orientation.Horizontal,
                Qt.ItemDataRole.DisplayRole,
            )
            or ""
        )
        metrics = header.fontMetrics()
        content_width = metrics.horizontalAdvance(title) + 28
        minimums = {
            "description": 180,
            "next_action": 160,
            "project_state": 120,
            "project_health": 120,
            "status": 100,
            "progress": 100,
            "reminder_at": 140,
            "last_update": 140,
        }
        key = self.model.column_key(logical)
        return max(minimums.get(key, 72), content_width)

    def _repair_task_header_section_widths(self):
        header = self.view.header()
        repaired = False
        for logical in range(self.proxy.columnCount()):
            if self.view.isColumnHidden(logical):
                continue
            current_width = header.sectionSize(logical)
            minimum_width = self._minimum_header_width_for_column(logical)
            if current_width < minimum_width:
                header.resizeSection(logical, int(minimum_width))
                repaired = True
        return repaired

    def _task_header_layout_signature_for_current_state(self) -> tuple:
        header = self.view.header()
        return (
            int(self.view.width()),
            int(header.width()),
            int(header.count()),
            self.view.font().toString(),
            tuple(bool(self.view.isColumnHidden(i)) for i in range(self.proxy.columnCount())),
        )

    def _apply_task_header_layout(self, *, force: bool = False):
        with measure_ui("main._apply_task_header_layout", visible=bool(self._is_task_table_visible())):
            if not hasattr(self, "view") or self.view.model() is None:
                return
            header = self.view.header()
            if header.count() <= 0:
                return
            if not self._is_task_table_visible():
                return
            if not force and not self.isVisible():
                return
            if not force and (self.view.width() <= 0 or header.width() <= 0):
                self._schedule_task_header_layout()
                return
            signature = self._task_header_layout_signature_for_current_state()
            repaired = self._repair_task_header_section_widths()
            if signature == self._task_header_layout_signature and not repaired:
                return
            self.view.updateGeometries()
            header.updateGeometry()
            if repaired:
                self.view.doItemsLayout()
            header.viewport().update()
            self.view.viewport().update()
            self._task_header_layout_signature = signature

    def _schedule_task_header_layout(self):
        if self._task_header_layout_pending:
            return
        self._task_header_layout_pending = True
        QTimer.singleShot(0, self._flush_task_header_layout)

    def _flush_task_header_layout(self):
        self._task_header_layout_pending = False
        self._apply_task_header_layout()

    # ---------- Restore / save UI state ----------
    def _restore_ui_settings(self):
        s = self.model.settings

        geo = s.value("ui/geometry")
        if geo is not None:
            self.restoreGeometry(geo)

        win_state = s.value("ui/window_state")
        if win_state is not None:
            self.restoreState(win_state)

        header_state = s.value("ui/header_state")
        restored_header = False
        if header_state is not None:
            try:
                restored_header = bool(self.view.header().restoreState(header_state))
            except Exception:
                restored_header = False
        if not restored_header:
            self._apply_default_column_widths()

        for logical in range(self.proxy.columnCount()):
            key = self.model.column_key(logical)
            hidden = s.value(f"columns/hidden/{key}", False, type=bool)
            self.view.setColumnHidden(logical, bool(hidden))

        self._schedule_task_header_layout()

        controls_visible = s.value("ui/controls_dock_visible", True, type=bool)
        self.controls_dock.setVisible(bool(controls_visible))
        if hasattr(self, "_toggle_controls_act"):
            self._toggle_controls_act.setChecked(bool(controls_visible))

        tree_floating = s.value("ui/tree_floating", False, type=bool)
        self._set_task_table_floating(bool(tree_floating), show_after=False)
        if bool(tree_floating):
            float_geo = s.value("ui/tree_float_geometry")
            if float_geo is not None and self._floating_table_window is not None:
                try:
                    self._floating_table_window.restoreGeometry(float_geo)
                except Exception:
                    pass

        tree_visible = s.value("ui/tree_visible", True, type=bool)
        self._set_tree_visible(bool(tree_visible), show_message=False)

        dock_visible = s.value("ui/filters_dock_visible", False, type=bool)
        self.filter_dock.setVisible(bool(dock_visible))
        self._toggle_filters_act.setChecked(bool(dock_visible))

        details_visible = s.value("ui/details_dock_visible", True, type=bool)
        self.details_dock.setVisible(bool(details_visible))
        if hasattr(self, "_toggle_details_act"):
            self._toggle_details_act.setChecked(bool(details_visible))

        project_visible = s.value("ui/project_dock_visible", False, type=bool)
        self.project_dock.setVisible(bool(project_visible))
        if hasattr(self, "_toggle_project_act"):
            self._toggle_project_act.setChecked(bool(project_visible))

        relationships_visible = s.value("ui/relationships_dock_visible", False, type=bool)
        self.relationships_dock.setVisible(bool(relationships_visible))
        if hasattr(self, "_toggle_relationships_act"):
            self._toggle_relationships_act.setChecked(bool(relationships_visible))

        undo_visible = s.value("ui/undo_dock_visible", False, type=bool)
        self.undo_dock.setVisible(bool(undo_visible))
        if hasattr(self, "_toggle_undo_history_act"):
            self._toggle_undo_history_act.setChecked(bool(undo_visible))

        focus_visible = s.value("ui/focus_dock_visible", False, type=bool)
        self.focus_dock.setVisible(bool(focus_visible))
        if hasattr(self, "_toggle_focus_act"):
            self._toggle_focus_act.setChecked(bool(focus_visible))

        cal_visible = s.value("ui/calendar_dock_visible", False, type=bool)
        self.calendar_dock.setVisible(bool(cal_visible))
        if hasattr(self, "_toggle_calendar_act"):
            self._toggle_calendar_act.setChecked(bool(cal_visible))

        review_visible = s.value("ui/review_dock_visible", False, type=bool)
        self.review_dock.setVisible(bool(review_visible))
        if hasattr(self, "_toggle_review_act"):
            self._toggle_review_act.setChecked(bool(review_visible))

        analytics_visible = s.value("ui/analytics_dock_visible", False, type=bool)
        self.analytics_dock.setVisible(bool(analytics_visible))
        if hasattr(self, "_toggle_analytics_act"):
            self._toggle_analytics_act.setChecked(bool(analytics_visible))

        perspective = str(s.value("ui/perspective", "all"))
        self._set_perspective_by_key(perspective)

        sort_mode = str(s.value("ui/sort_mode", "manual"))
        self._set_sort_mode_by_key(sort_mode)

        reminder_mode = str(s.value("ui/reminder_mode", self._reminder_mode))   
        self._set_reminder_mode(reminder_mode, show_message=False)

        self._apply_collapsed_state_to_view()
        self._refresh_calendar_list()
        self._refresh_calendar_markers()
        self._refresh_review_panel()
        self._refresh_focus_panel()
        self._refresh_analytics_panel()
        self._refresh_relationships_panel()
        self._apply_filters()

        self._schedule_row_action_button_update()

    def closeEvent(self, event):
        self._closing_down = True
        if not self._workspace_switching:
            self._save_ui_settings()
        s = self.model.settings
        if not self._workspace_switching and s.value("backup/on_close", True, type=bool):
            try:
                path = create_versioned_backup(self.db, "close")
                keep = s.value("backup/keep_count", 20, type=int)
                rotate_backups(max_keep=int(keep or 20), db_path=self.db.path)
                s.setValue("backup/last_snapshot_path", str(path))
                s.setValue("backup/last_snapshot_at", datetime.now().isoformat(timespec="seconds"))
                log_event(
                    "Close snapshot created",
                    context="backup.close",
                    db_path=self.db.path,
                    details={"path": str(path), "keep_count": int(keep or 20)},
                )
            except Exception as e:
                log_exception(e, context="close-backup", db_path=self.db.path)
                pass
        if self._tray_icon is not None:
            self._tray_icon.hide()
        if self._floating_table_window is not None:
            self._floating_table_window._allow_close = True
            self._floating_table_window.close()
        super().closeEvent(event)
        if event.isAccepted():
            try:
                self.db.close()
            except Exception as e:
                log_exception(e, context="db.close", db_path=self.db.path)


def main():
    try:
        log_event("Application startup requested", context="startup.begin", db_path=app_db_path())
        app = QApplication(sys.argv)
        app.setOrganizationName(APP_STORAGE_ORGANIZATION)
        app.setApplicationName(APP_STORAGE_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setApplicationVersion(APP_VERSION)

        workspace_manager = WorkspaceProfileManager()
        current_workspace = workspace_manager.current_workspace()
        workspace_manager.ensure_workspace_state(str(current_workspace.get("id") or "default"))
        workspace_manager.restore_state_for(str(current_workspace.get("id") or "default"))
        current_db_path = lambda: str(workspace_manager.current_workspace().get("db_path") or app_db_path())
        install_exception_hooks(current_db_path)

        w = MainWindow(workspace_manager, str(current_workspace.get("id") or "default"))
        w.resize(1100, 650)
        w.show()
        log_event(
            "Application main window shown",
            context="startup.ready",
            db_path=current_db_path(),
            details={"workspace_id": str(current_workspace.get("id") or "default")},
        )

        # Close splash again after show (covers slow first paint)
        try:
            import pyi_splash  # type: ignore
            pyi_splash.close()
        except Exception:
            pass

        return app.exec()
    except DatabaseMigrationError as e:
        log_exception(e, context="startup-migration", db_path=app_db_path())
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                "Database migration failed",
                f"The task database could not be opened safely.\n\n{e}",
            )
        else:
            print(f"Database migration failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        log_exception(e, context="startup", db_path=app_db_path())
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                "Application startup failed",
                f"{APP_NAME} could not start.\n\n{e}",
            )
        else:
            print(f"{APP_NAME} startup failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
