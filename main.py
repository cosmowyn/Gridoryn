import sys
from datetime import date, datetime, timedelta

# --- PyInstaller splash: close it ASAP (safe when not built with --splash) ---
try:
    import pyi_splash  # type: ignore
    pyi_splash.close()
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer, QModelIndex, QEvent, QDateTime, QUrl
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QPushButton, QToolBar, QMenu, QMessageBox,
    QLineEdit, QDockWidget, QLabel, QToolButton, QComboBox, QInputDialog,
    QFileDialog, QListWidget, QListWidgetItem, QUndoView, QScrollArea,
    QGridLayout, QGroupBox
)

from app_paths import app_db_path
from db import Database
from model import TaskTreeModel, STATUSES
from delegates import install_delegates
from settings_ui import SettingsDialog
from columns_ui import AddColumnDialog, RemoveColumnDialog
from filter_proxy import TaskFilterProxyModel
from filters_ui import FilterPanel
from query_parsing import parse_quick_add
from details_panel import TaskDetailsPanel
from auto_backup import create_versioned_backup, rotate_backups
from help_ui import HelpDialog
from calendar_widgets import TaskCalendarWidget
from reminders_ui import ReminderBatchDialog
from archive_ui import ArchiveBrowserDialog
from command_palette import CommandPaletteDialog, PaletteCommand
from review_ui import ReviewWorkflowPanel
from template_params import collect_template_placeholders, apply_template_values
from template_vars_ui import TemplateVariablesDialog
from analytics_ui import AnalyticsPanel

from backup_io import export_backup_ui, import_backup_ui
from theme_io import export_themes_ui, import_themes_ui
from ui_layout import add_left_aligned_buttons, configure_box_layout, configure_grid_layout


class MainWindow(QMainWindow):
    REMINDER_MODE_NORMAL = "normal"
    REMINDER_MODE_MUTE_ALL = "mute_all"
    REMINDER_MODE_PRIORITY1_ONLY = "priority1_only"

    def __init__(self):
        super().__init__()

        self.setWindowTitle("CustomTaskManager")

        self.db = Database(app_db_path())

        # Source model (full tree)
        self.model = TaskTreeModel(self.db)
        self.undo_stack = self.model.undo_stack
        self._tooltips_enabled = True
        self._help_dialog: HelpDialog | None = None
        self._reminder_mode = str(
            self.model.settings.value("ui/reminder_mode", self.REMINDER_MODE_NORMAL)
        ).strip() or self.REMINDER_MODE_NORMAL
        self._reminder_prompt_cooldown_until: datetime | None = None
        self._reminder_dialog_open = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

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
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.view.setHorizontalScrollMode(QTreeView.ScrollMode.ScrollPerPixel)
        self.view.setVerticalScrollMode(QTreeView.ScrollMode.ScrollPerPixel)
        self.view.setAcceptDrops(True)
        self.view.viewport().setAcceptDrops(True)

        hdr = self.view.header()
        hdr.setSectionsMovable(True)
        hdr.setStretchLastSection(False)

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
        self.quick_add.setPlaceholderText("Quick add... e.g. Call supplier next week p1 (Ctrl+L)")
        self.quick_add.returnPressed.connect(self._quick_add_submit)

        self.view_mode = QComboBox()
        for title, key in self._perspectives:
            self.view_mode.addItem(title, key)
        self.view_mode.currentIndexChanged.connect(self._on_perspective_changed)

        self.sort_mode = QComboBox()
        for title, key in self._sort_modes:
            self.sort_mode.addItem(title, key)
        self.sort_mode.currentIndexChanged.connect(self._on_sort_mode_changed)

        control_h = max(26, self.fontMetrics().height() + 10)
        for w in (self.quick_add, self.view_mode, self.sort_mode):
            w.setMinimumHeight(control_h)

        # --- Search bar (above the view)
        self.search = QLineEdit()
        self.search.setObjectName("SearchBar")
        self.search.setPlaceholderText("Search… (Ctrl+F)  status:todo priority:1 due<=today tag:work has:children")
        self.search.textChanged.connect(self._on_search_changed)
        self.search.setMinimumHeight(control_h)

        clear_btn = QToolButton()
        clear_btn.setObjectName("SearchClear")
        clear_btn.setText("✕")
        clear_btn.setToolTip("Clear search")
        clear_btn.clicked.connect(lambda: self.search.setText(""))
        clear_btn.setMinimumHeight(control_h)

        add_btn = QPushButton("Add task")
        add_btn.clicked.connect(self._add_task_and_edit)
        add_btn.setMinimumHeight(control_h)

        # Layout
        main = QWidget()
        v = QVBoxLayout(main)
        configure_box_layout(v, margins=(8, 8, 8, 8), spacing=8)

        top_controls = QGroupBox("Capture and navigation")
        top_layout = QGridLayout(top_controls)
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

        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        top_scroll.setWidget(top_controls)
        top_scroll.setMaximumHeight((control_h * 2) + 56)
        v.addWidget(top_scroll, 0)

        self._row_gutter = QWidget()
        self._row_gutter.setObjectName("RowActionGutter")
        self._row_gutter.setFixedWidth(self._row_action_gutter)

        tree_row = QHBoxLayout()
        tree_row.setContentsMargins(0, 0, 0, 0)
        tree_row.setSpacing(0)
        tree_row.addWidget(self._row_gutter)
        tree_row.addWidget(self.view, 1)

        tree_wrap = QWidget()
        tree_wrap.setLayout(tree_row)
        v.addWidget(tree_wrap, 1)

        h = QHBoxLayout()
        add_left_aligned_buttons(h, add_btn)
        v.addLayout(h)

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
        self.view.verticalScrollBar().valueChanged.connect(lambda *_: self._update_row_action_buttons())
        self.view.horizontalScrollBar().valueChanged.connect(lambda *_: self._update_row_action_buttons())
        self.view.header().geometriesChanged.connect(lambda: self._update_row_action_buttons())
        self.view.viewport().installEventFilter(self)
        self.view.installEventFilter(self)

        # Advanced filter panel (dock)
        self._init_filter_dock()
        self._init_details_dock()
        self._init_undo_history_dock()
        self._init_calendar_dock()
        self._init_review_dock()
        self._init_analytics_dock()

        self._build_menus_and_toolbar()
        self._apply_widget_tooltips()
        self._restore_ui_settings()
        tooltips_enabled = self.model.settings.value("ui/tooltips_enabled", True, type=bool)
        self._set_tooltips_enabled(bool(tooltips_enabled), show_message=False)

        self.model.modelReset.connect(self._apply_collapsed_state_to_view)
        self.proxy.modelReset.connect(self._apply_collapsed_state_to_view)
        self.model.modelReset.connect(self._refresh_calendar_list)
        self.model.modelReset.connect(self._refresh_calendar_markers)
        self.model.modelReset.connect(self._refresh_review_panel)
        self.model.modelReset.connect(self._refresh_analytics_panel)
        self.model.modelReset.connect(self._refresh_details_dock)
        self.model.dataChanged.connect(lambda *_: self._refresh_calendar_markers())
        self.model.rowsInserted.connect(lambda *_: self._refresh_calendar_markers())
        self.model.rowsRemoved.connect(lambda *_: self._refresh_calendar_markers())

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
        focus_search.setShortcut(QKeySequence(Qt.CTRL | Qt.Key.Key_F))
        focus_search.triggered.connect(lambda: self.search.setFocus())
        self.addAction(focus_search)

        focus_quick_add = QAction(self)
        focus_quick_add.setShortcut(QKeySequence(Qt.CTRL | Qt.Key.Key_L))
        focus_quick_add.triggered.connect(lambda: self.quick_add.setFocus())
        self.addAction(focus_quick_add)

        QTimer.singleShot(0, self._update_row_action_buttons)
        QTimer.singleShot(0, self._refresh_details_dock)

    # ---------- Splash (close again once UI shows) ----------
    def showEvent(self, event):
        super().showEvent(event)
        try:
            import pyi_splash  # type: ignore
            pyi_splash.close()
        except Exception:
            pass

    # ---------- Event filter for overlay alignment ----------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ToolTip and not self._tooltips_enabled:
            return True
        if hasattr(self, "view") and obj in (self.view.viewport(), self.view):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Wheel, QEvent.Type.Move, QEvent.Type.Show):
                QTimer.singleShot(0, self._update_row_action_buttons)
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
                            for p in paths:
                                try:
                                    self.model.add_attachment(int(tid), p, "")
                                except Exception:
                                    continue
                            self._refresh_details_dock()
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def _row_button_size(self) -> int:
        h = self.view.fontMetrics().height()
        return max(18, min(28, h + 6))

    def _update_row_action_buttons(self):
        idx = self.view.currentIndex()
        if not idx.isValid():
            self.row_add_btn.hide()
            self.row_del_btn.hide()
            return

        idx0 = idx.siblingAtColumn(0)
        rect = self.view.visualRect(idx0)
        vp_rect = self.view.viewport().rect()

        if rect.isNull() or rect.height() <= 0 or not rect.intersects(vp_rect):
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

        self.row_add_btn.move(x_add, y)
        self.row_del_btn.move(x_del, y)

        self.row_add_btn.show()
        self.row_del_btn.show()
        self.row_add_btn.raise_()
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
        QTimer.singleShot(0, self._update_row_action_buttons)

    def _row_delete_clicked(self):
        self._archive_selected()
        QTimer.singleShot(0, self._update_row_action_buttons)

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

    def _quick_add_submit(self):
        raw = self.quick_add.text().strip()
        if not raw:
            return
        parsed = parse_quick_add(raw)
        if not parsed.description:
            parsed.description = raw

        perspective = str(self.view_mode.currentData() or "all")
        bucket = perspective if perspective in {"inbox", "today", "upcoming", "someday"} else "inbox"

        ok = self.model.add_task_with_values(
            description=parsed.description,
            due_date=parsed.due_date,
            priority=parsed.priority,
            parent_id=None,
            planned_bucket=bucket,
        )
        if ok:
            new_id = self.model.last_added_task_id()
            self.quick_add.clear()
            if new_id is not None:
                before = self._selected_task_id()
                self._focus_task_by_id(int(new_id))
                after = self._selected_task_id()
                if after != int(new_id):
                    self.statusBar().showMessage(
                        "Task created, but hidden by current view/filter.",
                        4000,
                    )
                elif before != after:
                    self._refresh_details_dock()
        self.quick_add.setFocus()

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
        QTimer.singleShot(0, self._update_row_action_buttons)

    # ---------- Filters ----------
    def _init_filter_dock(self):
        self.filter_panel = FilterPanel(STATUSES, self)
        self.filter_panel.changed.connect(self._apply_filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self.filter_panel)

        self.filter_dock = QDockWidget("Filters", self)
        self.filter_dock.setObjectName("FiltersDock")
        self.filter_dock.setWidget(scroll)
        self.filter_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.filter_dock)
        self.filter_dock.hide()
        self.filter_dock.visibilityChanged.connect(
            lambda vis: self._toggle_filters_act.setChecked(bool(vis)) if hasattr(self, "_toggle_filters_act") else None
        )

    def _init_details_dock(self):
        self.details_panel = TaskDetailsPanel(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self.details_panel)

        self.details_dock = QDockWidget("Details", self)
        self.details_dock.setObjectName("DetailsDock")
        self.details_dock.setWidget(scroll)
        self.details_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.details_dock)

        self.details_panel.save_btn.clicked.connect(self._save_details_from_panel)
        self.details_panel.start_timer_btn.clicked.connect(self._details_start_timer)
        self.details_panel.stop_timer_btn.clicked.connect(self._details_stop_timer)
        self.details_panel.set_reminder_btn.clicked.connect(self._details_set_reminder)
        self.details_panel.set_due_reminder_btn.clicked.connect(self._details_set_due_reminder)
        self.details_panel.clear_reminder_btn.clicked.connect(self._details_clear_reminder)
        self.details_panel.add_file_btn.clicked.connect(self._details_add_file_attachment)
        self.details_panel.add_folder_btn.clicked.connect(self._details_add_folder_attachment)
        self.details_panel.open_attachment_btn.clicked.connect(self._details_open_attachment)
        self.details_panel.remove_attachment_btn.clicked.connect(self._details_remove_attachment)

        self.details_dock.visibilityChanged.connect(
            lambda vis: self._toggle_details_act.setChecked(bool(vis)) if hasattr(self, "_toggle_details_act") else None
        )

    def _init_undo_history_dock(self):
        self.undo_view = QUndoView(self.undo_stack, self)
        self.undo_view.setObjectName("UndoHistoryView")
        self.undo_dock = QDockWidget("Undo History", self)
        self.undo_dock.setObjectName("UndoHistoryDock")
        self.undo_dock.setWidget(self.undo_view)
        self.undo_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.undo_dock)
        self.undo_dock.hide()
        self.undo_dock.visibilityChanged.connect(
            lambda vis: self._toggle_undo_history_act.setChecked(bool(vis))
            if hasattr(self, "_toggle_undo_history_act")
            else None
        )

    def _init_review_dock(self):
        self.review_panel = ReviewWorkflowPanel(self)
        self.review_panel.refreshRequested.connect(self._refresh_review_panel)
        self.review_panel.focusTaskRequested.connect(self._review_focus_task)
        self.review_panel.markDoneRequested.connect(self._review_mark_done)
        self.review_panel.archiveRequested.connect(self._review_archive)
        self.review_panel.restoreRequested.connect(self._review_restore)

        self.review_dock = QDockWidget("Review Workflow", self)
        self.review_dock.setObjectName("ReviewDock")
        self.review_dock.setWidget(self.review_panel)
        self.review_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
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
        self.analytics_dock.setWidget(self.analytics_panel)
        self.analytics_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
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

        calendar_group = QGroupBox("Calendar")
        calendar_layout = QVBoxLayout(calendar_group)
        configure_box_layout(calendar_layout)
        self.calendar = TaskCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(self.calendar.VerticalHeaderFormat.ISOWeekNumbers)
        self.calendar.selectionChanged.connect(self._refresh_calendar_list)
        self.calendar.currentPageChanged.connect(lambda *_: self._refresh_calendar_markers())
        calendar_layout.addWidget(self.calendar)
        v.addWidget(calendar_group)

        agenda_group = QGroupBox("Agenda")
        agenda_layout = QVBoxLayout(agenda_group)
        configure_box_layout(agenda_layout)
        self.calendar_list = QListWidget()
        self.calendar_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.calendar_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.calendar_list.itemActivated.connect(self._on_calendar_task_activated)
        self.calendar_list.itemDoubleClicked.connect(self._on_calendar_task_activated)
        agenda_layout.addWidget(self.calendar_list, 1)
        v.addWidget(agenda_group, 1)

        self.calendar_dock = QDockWidget("Calendar / Agenda", self)
        self.calendar_dock.setObjectName("CalendarDock")
        self.calendar_dock.setWidget(wrap)
        self.calendar_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.calendar_dock)
        self.calendar_dock.hide()
        self.calendar_dock.visibilityChanged.connect(
            lambda vis: self._toggle_calendar_act.setChecked(bool(vis)) if hasattr(self, "_toggle_calendar_act") else None
        )

    def _refresh_details_dock(self):
        tid = self._selected_task_id()
        if tid is None:
            self.details_panel.set_task_details(None)
            return
        details = self.model.task_details(int(tid))
        self.details_panel.set_task_details(details)

    def _save_details_from_panel(self):
        tid = self.details_panel.task_id()
        if tid is None:
            return
        payload = self.details_panel.collect_payload()
        self.model.set_task_notes(int(tid), payload["notes"])
        self.model.set_task_tags(int(tid), payload["tags"])
        self.model.set_task_bucket(int(tid), payload["bucket"])
        self.model.set_task_waiting_for(int(tid), payload["waiting_for"])
        self.model.set_task_dependencies(int(tid), payload["dependencies"])
        self.model.set_task_recurrence(
            int(tid),
            payload["recurrence"],
            bool(payload["recurrence_next_on_done"]),
        )
        self.model.set_task_effort_minutes(int(tid), payload["effort_minutes"])
        self.model.set_task_actual_minutes(int(tid), payload["actual_minutes"])
        self._refresh_details_dock()
        self._refresh_calendar_list()

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
        for p in paths:
            try:
                self.model.add_attachment(int(tid), p, "")
            except Exception:
                continue
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
        if not hasattr(self, "calendar"):
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
            by_date = {str(r.get("due_date") or ""): float(r.get("percent") or 0.0) for r in rows}
            self.calendar.set_completion_summary(by_date)
        except Exception:
            self.calendar.set_completion_summary({})

    def _refresh_calendar_list(self):
        if not hasattr(self, "calendar_list"):
            return
        self.calendar_list.clear()
        day_iso = self.calendar.selectedDate().toString("yyyy-MM-dd")
        for task in self.db.fetch_tasks_due_on(day_iso, include_archived=False):
            txt = f"[P{task.get('priority', '')}] {task.get('description', '')} ({task.get('status', '')})"
            it = QListWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, int(task["id"]))
            self.calendar_list.addItem(it)

    def _on_calendar_task_activated(self, item):
        if not item:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        try:
            tid = int(tid)
        except Exception:
            return
        self._focus_task_by_id(tid)

    def _refresh_review_panel(
        self,
        waiting_days: int | None = None,
        stalled_days: int | None = None,
        recent_days: int | None = None,
    ):
        if not hasattr(self, "review_panel"):
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
        self.review_panel.set_review_data(data)

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

    def _refresh_analytics_panel(self, trend_days: int | None = None, tag_days: int | None = None):
        if not hasattr(self, "analytics_panel"):
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
        QTimer.singleShot(0, self._update_row_action_buttons)

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
        QTimer.singleShot(0, self._update_row_action_buttons)

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
                for r in pending:
                    try:
                        self.model.mark_reminder_fired(int(r["id"]))
                    except Exception:
                        continue
                self._reminder_prompt_cooldown_until = None
                return

            if action == ReminderBatchDialog.ACTION_SNOOZE:
                snooze_iso = dlg.snooze_iso()
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
            create_versioned_backup(self.db, "auto")
            rotate_backups(max_keep=int(keep or 20))
        except Exception:
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

    def _create_backup_now(self):
        try:
            path = create_versioned_backup(self.db, "manual")
            keep = self.model.settings.value("backup/keep_count", 20, type=int)
            rotate_backups(max_keep=int(keep or 20))
            QMessageBox.information(self, "Backup created", f"Snapshot saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Backup failed", str(e))

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
        names = [str(t.get("name")) for t in templates if str(t.get("name") or "").strip()]
        if not names:
            QMessageBox.information(self, "No templates", "There are no saved templates.")
            return
        name, ok = QInputDialog.getItem(self, "Delete template", "Template", names, 0, False)
        if not ok or not name:
            return
        self.model.delete_template(str(name))

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
            PaletteCommand("ui.focus_search", "Focus search", "Move cursor to search box", ("search", "find"), lambda: self.search.setFocus()),
            PaletteCommand("ui.focus_quick_add", "Focus quick add", "Move cursor to quick-add input", ("quick add", "capture"), lambda: self.quick_add.setFocus()),
            PaletteCommand("backup.export_data", "Export backup data", "Open data export dialog", ("backup", "export"), lambda: export_backup_ui(self, self.db)),
            PaletteCommand("backup.import_data", "Import backup data", "Open data import dialog", ("backup", "import"), lambda: import_backup_ui(self)),
            PaletteCommand("theme.export", "Export themes", "Open theme export dialog", ("theme", "export"), lambda: export_themes_ui(self, self.model.settings)),
            PaletteCommand(
                "theme.import",
                "Import themes",
                "Open theme import dialog",
                ("theme", "import"),
                lambda: import_themes_ui(self, self.model.settings, apply_callback=lambda: self._apply_theme_now()),
            ),
        ]

        # Perspective jumps
        for label, key in self._perspectives:
            if key == "all":
                continue
            commands.append(
                PaletteCommand(
                    f"perspective.{key}",
                    f"Jump to {label}",
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
            (self.quick_add, "Quick-add task input. Supports due date and priority keywords."),
            (self.search, "Search tasks with free text and operators like status:, due<=, tag:, has:."),
            (self.view_mode, "Choose a built-in perspective: All, Today, Upcoming, Inbox, Someday, Completed/Archive."),
            (self.sort_mode, "Choose how tasks are sorted in the current view."),
            (self.view, "Main task tree. Select rows, edit cells, and organize hierarchy."),
            (self.row_add_btn, "Add child task to the focused row."),
            (self.row_del_btn, "Archive focused row."),
            (self.filter_panel, "Advanced filtering controls."),
            (self.details_panel, "Task details editor for notes, tags, recurrence, reminders, and attachments."),
            (self.undo_view, "Undo history list. Click an entry to inspect/step through history."),
            (self.calendar, "Calendar navigator for due-date agenda."),
            (self.calendar_list, "Tasks due on selected calendar date."),
            (self.review_panel, "Guided weekly/daily review workspace with actionable categories."),
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

    # ---------- Menus / toolbar ----------
    def _build_menus_and_toolbar(self):
        undo_act = QAction("Undo", self)
        undo_act.setShortcut(QKeySequence.StandardKey.Undo)
        undo_act.triggered.connect(self.undo_stack.undo)

        redo_act = QAction("Redo", self)
        redo_act.setShortcut(QKeySequence.StandardKey.Redo)
        redo_act.triggered.connect(self.undo_stack.redo)

        add_act = QAction("Add task", self)
        add_act.setShortcut(QKeySequence(Qt.CTRL | Qt.Key.Key_N))
        add_act.triggered.connect(self._add_task_and_edit)

        add_child_act = QAction("Add child task", self)
        add_child_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_N))
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
        browse_archive_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_R))
        browse_archive_act.triggered.connect(self._open_archive_browser)

        duplicate_act = QAction("Duplicate task", self)
        duplicate_act.setShortcut(QKeySequence(Qt.CTRL | Qt.Key.Key_D))
        duplicate_act.triggered.connect(self._duplicate_selected)

        duplicate_tree_act = QAction("Duplicate with children", self)
        duplicate_tree_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_D))
        duplicate_tree_act.triggered.connect(self._duplicate_selected_subtree)

        bulk_edit_act = QAction("Bulk edit…", self)
        bulk_edit_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_B))
        bulk_edit_act.triggered.connect(self._bulk_edit_selected)

        settings_act = QAction("Settings & Themes…", self)
        settings_act.triggered.connect(self._open_settings)

        toggle_filters_act = QAction("Filters panel", self)
        toggle_filters_act.setCheckable(True)
        toggle_filters_act.setChecked(False)
        toggle_filters_act.triggered.connect(self._toggle_filters_dock)

        toggle_details_act = QAction("Details panel", self)
        toggle_details_act.setCheckable(True)
        toggle_details_act.setChecked(True)
        toggle_details_act.triggered.connect(lambda checked: self.details_dock.setVisible(bool(checked)))

        toggle_undo_history_act = QAction("Undo history", self)
        toggle_undo_history_act.setCheckable(True)
        toggle_undo_history_act.setChecked(False)
        toggle_undo_history_act.triggered.connect(lambda checked: self.undo_dock.setVisible(bool(checked)))

        toggle_calendar_act = QAction("Calendar/agenda", self)
        toggle_calendar_act.setCheckable(True)
        toggle_calendar_act.setChecked(False)
        toggle_calendar_act.triggered.connect(lambda checked: self.calendar_dock.setVisible(bool(checked)))

        toggle_review_act = QAction("Review workflow", self)
        toggle_review_act.setCheckable(True)
        toggle_review_act.setChecked(False)
        toggle_review_act.triggered.connect(lambda checked: self.review_dock.setVisible(bool(checked)))

        toggle_analytics_act = QAction("Analytics", self)
        toggle_analytics_act.setCheckable(True)
        toggle_analytics_act.setChecked(False)
        toggle_analytics_act.triggered.connect(lambda checked: self.analytics_dock.setVisible(bool(checked)))

        collapse_all_act = QAction("Collapse all", self)
        collapse_all_act.setShortcut(QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key.Key_Up))
        collapse_all_act.triggered.connect(self._collapse_all)

        expand_all_act = QAction("Expand all", self)
        expand_all_act.setShortcut(QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key.Key_Down))
        expand_all_act.triggered.connect(self._expand_all)

        move_up_act = QAction("Move task up", self)
        move_up_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_Up))
        move_up_act.triggered.connect(lambda: self._move_selected_relative(-1))

        move_down_act = QAction("Move task down", self)
        move_down_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_Down))
        move_down_act.triggered.connect(lambda: self._move_selected_relative(1))

        # Keyboard-first workflow shortcuts.
        edit_current_act = QAction("Edit current", self)
        edit_current_act.setShortcut(QKeySequence(Qt.Key.Key_Return))
        edit_current_act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        edit_current_act.triggered.connect(self._edit_current_cell)

        edit_current_numpad_act = QAction("Edit current (numpad)", self)
        edit_current_numpad_act.setShortcut(QKeySequence(Qt.Key.Key_Enter))
        edit_current_numpad_act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
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

        command_palette_act = QAction("Command palette…", self)
        command_palette_act.setShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key.Key_P))
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
        m_file.addAction(settings_act)

        # Backup submenu (data + themes)
        m_backup = m_file.addMenu("Backup")

        export_db_act = QAction("Export Data…", self)
        export_db_act.triggered.connect(lambda: export_backup_ui(self, self.db))
        m_backup.addAction(export_db_act)

        import_db_act = QAction("Import Data…", self)
        import_db_act.triggered.connect(lambda: import_backup_ui(self))
        m_backup.addAction(import_db_act)

        m_backup.addSeparator()

        export_theme_act = QAction("Export Themes…", self)
        export_theme_act.triggered.connect(lambda: export_themes_ui(self, self.model.settings))
        m_backup.addAction(export_theme_act)

        import_theme_act = QAction("Import Themes…", self)
        import_theme_act.triggered.connect(
            lambda: import_themes_ui(
                self,
                self.model.settings,
                apply_callback=lambda: self._apply_theme_now(),
            )
        )
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
        m_view.addAction(toggle_filters_act)
        m_view.addAction(toggle_details_act)
        m_view.addAction(toggle_undo_history_act)
        m_view.addAction(toggle_calendar_act)
        m_view.addAction(toggle_review_act)
        m_view.addAction(toggle_analytics_act)
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
        m_tools.addAction(command_palette_act)
        m_tools.addSeparator()
        m_tools.addAction(save_template_act)
        m_tools.addAction(create_template_act)
        m_tools.addAction(delete_template_act)

        m_help = menubar.addMenu("Help")
        m_help.addAction(help_act)
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
        tb.addAction(add_child_act)
        tb.addAction(archive_act)
        tb.addAction(duplicate_act)
        tb.addSeparator()
        tb.addAction(undo_act)
        tb.addAction(redo_act)

        self._toggle_filters_act = toggle_filters_act
        self._toggle_details_act = toggle_details_act
        self._toggle_undo_history_act = toggle_undo_history_act
        self._toggle_calendar_act = toggle_calendar_act
        self._toggle_review_act = toggle_review_act
        self._toggle_analytics_act = toggle_analytics_act
        self._toggle_tooltips_act = toggle_tooltips_act

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
        self.addAction(move_up_act)
        self.addAction(move_down_act)
        self.addAction(command_palette_act)
        self.addAction(browse_archive_act)
        self.view.addAction(edit_current_act)
        self.view.addAction(edit_current_numpad_act)
        self.addAction(toggle_expand_act)
        self.addAction(help_act)

        # Action help text for tooltips/status bar guidance.
        action_help: list[tuple[QAction, str]] = [
            (undo_act, "Undo the most recent change."),
            (redo_act, "Redo the next change in history."),
            (add_act, "Create a new top-level task."),
            (add_child_act, "Create a child task under the selected row."),
            (archive_act, "Archive selected task(s)."),
            (hard_del_act, "Permanently delete selected task(s)."),
            (restore_act, "Restore selected archived task(s)."),
            (browse_archive_act, "Open archive browser and choose tasks to restore."),
            (duplicate_act, "Duplicate the selected task."),
            (duplicate_tree_act, "Duplicate selected task with all descendants."),
            (bulk_edit_act, "Apply one operation to multiple selected tasks."),
            (toggle_filters_act, "Show or hide the Filters dock."),
            (toggle_details_act, "Show or hide the Details dock."),
            (toggle_undo_history_act, "Show or hide the Undo History dock."),
            (toggle_calendar_act, "Show or hide the Calendar/Agenda dock."),
            (toggle_review_act, "Show or hide the guided Review Workflow dock."),
            (toggle_analytics_act, "Show or hide analytics summary dashboard."),
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
            (backup_settings_act, "Configure automatic backup interval and retention."),
            (backup_now_act, "Create a versioned backup snapshot now."),
            (command_palette_act, "Open the searchable command palette for keyboard-first actions."),
            (help_act, "Open the embedded help guide with indexed chapters."),
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
        QTimer.singleShot(0, self._update_row_action_buttons)

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
                    QTimer.singleShot(0, self._update_row_action_buttons)
                return _toggle

            act.triggered.connect(make_toggle(logical, key))
            self.m_columns.addAction(act)

    # ---------- Expand / collapse all ----------
    def _collapse_all(self):
        self.view.collapseAll()
        for node in self.model.iter_nodes_preorder():
            if node.task:
                self.model.set_collapsed(int(node.task["id"]), True)
        QTimer.singleShot(0, self._update_row_action_buttons)

    def _expand_all(self):
        self.view.expandAll()
        for node in self.model.iter_nodes_preorder():
            if node.task:
                self.model.set_collapsed(int(node.task["id"]), False)
        QTimer.singleShot(0, self._update_row_action_buttons)

    # ---------- Context menu + selection helpers ----------
    def _open_context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)

        src = self.proxy.mapToSource(index)
        task_id = self.model.task_id_from_index(src)
        if task_id is None:
            return

        menu = QMenu(self)

        add_child = QAction("Add child task", self)
        add_child.triggered.connect(self._add_child_to_selected)
        menu.addAction(add_child)

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

    def _archive_selected(self):
        ids = self._selected_task_ids()
        if not ids:
            return
        self.model.archive_tasks(ids)
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
        self.model.hard_delete_tasks(ids)
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

        QTimer.singleShot(0, self._update_row_action_buttons)

    def _on_current_changed(self, *_):
        self._update_row_action_buttons()
        self._refresh_details_dock()

    def _set_perspective_by_key(self, key: str):
        for i in range(self.view_mode.count()):
            if self.view_mode.itemData(i) == key:
                self.view_mode.setCurrentIndex(i)
                return
        self.view_mode.setCurrentIndex(0)

    def _on_perspective_changed(self, *_):
        key = str(self.view_mode.currentData() or "all")
        self.proxy.set_perspective(key)
        self.model.settings.setValue("ui/perspective", key)
        self._update_dragdrop_mode()
        self._refresh_calendar_list()
        QTimer.singleShot(0, self._update_row_action_buttons)

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
        QTimer.singleShot(0, self._update_row_action_buttons)

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

    def _focus_task_by_id(self, task_id: int):
        src = self._source_index_for_task_id(int(task_id), 0)
        if not src.isValid():
            return
        pidx = self.proxy.mapFromSource(src)
        if not pidx.isValid():
            return
        self.view.setCurrentIndex(pidx)
        self.view.scrollTo(pidx)

    def _edit_current_cell(self):
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
            QTimer.singleShot(0, self._update_row_action_buttons)

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
            for tid in ids:
                details = self.model.task_details(int(tid)) or {}
                existing = list(details.get("tags") or [])
                merged = existing[:]
                lower = {x.lower() for x in existing}
                for t in tags_to_add:
                    if t.lower() not in lower:
                        merged.append(t)
                self.model.set_task_tags(int(tid), merged)
            return

        if op == "Remove tags":
            value, ok = QInputDialog.getText(self, "Remove tags", "Tags to remove (comma-separated):")
            if not ok:
                return
            tags_to_remove = {x.strip().lower() for x in str(value or "").split(",") if x.strip()}
            if not tags_to_remove:
                return
            for tid in ids:
                details = self.model.task_details(int(tid)) or {}
                existing = list(details.get("tags") or [])
                keep = [x for x in existing if x.lower() not in tags_to_remove]
                self.model.set_task_tags(int(tid), keep)
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
        self.model.refresh_due_highlights()

    def _open_settings(self):
        dlg = SettingsDialog(self.model.settings, self)
        if dlg.exec():
            self._apply_theme_now()
            QTimer.singleShot(0, self._update_row_action_buttons)

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
        QTimer.singleShot(0, self._update_row_action_buttons)

    def _on_expanded(self, proxy_index):
        if self._applying_expand_state:
            return
        src = self.proxy.mapToSource(proxy_index)
        task_id = self.model.task_id_from_index(src)
        if task_id is not None:
            self.model.set_collapsed(task_id, False)
        QTimer.singleShot(0, self._update_row_action_buttons)

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

        QTimer.singleShot(0, self._update_row_action_buttons)

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
        }
        for logical in range(self.proxy.columnCount()):
            key = self.model.column_key(logical)
            w = widths.get(key)
            if w is not None:
                self.view.setColumnWidth(logical, int(w))

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

        dock_visible = s.value("ui/filters_dock_visible", False, type=bool)
        self.filter_dock.setVisible(bool(dock_visible))
        self._toggle_filters_act.setChecked(bool(dock_visible))

        details_visible = s.value("ui/details_dock_visible", True, type=bool)
        self.details_dock.setVisible(bool(details_visible))
        if hasattr(self, "_toggle_details_act"):
            self._toggle_details_act.setChecked(bool(details_visible))

        undo_visible = s.value("ui/undo_dock_visible", False, type=bool)
        self.undo_dock.setVisible(bool(undo_visible))
        if hasattr(self, "_toggle_undo_history_act"):
            self._toggle_undo_history_act.setChecked(bool(undo_visible))

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
        self._refresh_analytics_panel()
        self._apply_filters()

        QTimer.singleShot(0, self._update_row_action_buttons)

    def closeEvent(self, event):
        s = self.model.settings
        s.setValue("ui/geometry", self.saveGeometry())
        s.setValue("ui/window_state", self.saveState())
        s.setValue("ui/header_state", self.view.header().saveState())
        s.setValue("ui/filters_dock_visible", self.filter_dock.isVisible())
        s.setValue("ui/details_dock_visible", self.details_dock.isVisible())
        s.setValue("ui/undo_dock_visible", self.undo_dock.isVisible())
        s.setValue("ui/calendar_dock_visible", self.calendar_dock.isVisible())
        s.setValue("ui/review_dock_visible", self.review_dock.isVisible())
        s.setValue("ui/analytics_dock_visible", self.analytics_dock.isVisible())
        s.setValue("ui/tooltips_enabled", self._tooltips_enabled)
        s.setValue("ui/perspective", str(self.view_mode.currentData() or "all"))
        s.setValue("ui/sort_mode", str(self.sort_mode.currentData() or "manual"))
        s.setValue("ui/reminder_mode", self._reminder_mode)
        if s.value("backup/on_close", True, type=bool):
            try:
                create_versioned_backup(self.db, "close")
                keep = s.value("backup/keep_count", 20, type=int)
                rotate_backups(max_keep=int(keep or 20))
            except Exception:
                pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("FocusTools")
    app.setApplicationName("CustomTaskManager")

    w = MainWindow()
    w.resize(1100, 650)
    w.show()

    # Close splash again after show (covers slow first paint)
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
