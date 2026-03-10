from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QHeaderView, QMenu, QStyle, QStyleOptionViewItem

import main as main_module
from db import Database
from main import MainWindow
from workspace_profiles import WorkspaceProfileManager


def _build_window(tmp_path, qapp, monkeypatch):
    QSettings().setValue("ui/onboarding_completed", True)
    monkeypatch.setattr(main_module.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    monkeypatch.setattr(MainWindow, "_install_optional_global_capture_hotkey", lambda self: None)
    manager = WorkspaceProfileManager(base_dir=str(tmp_path / "workspace-data"))
    workspace = manager.create_workspace(
        "Task Browser Test",
        db_path=str(tmp_path / "task-browser.sqlite3"),
        inherit_current_state=False,
    )
    manager.set_current_workspace(str(workspace["id"]))
    window = MainWindow(manager, str(workspace["id"]))
    window.show()
    qapp.processEvents()
    return window


def _rightmost_visible_section(window):
    header = window.view.header()
    visible = [i for i in range(header.count()) if not window.view.isColumnHidden(i)]
    return max(
        visible,
        key=lambda logical: header.sectionPosition(logical) + header.sectionSize(logical),
    )


def test_task_table_toggle_and_side_panel_browsing(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.controls_dock.isVisible()
        window.controls_dock.hide()
        qapp.processEvents()
        assert not window.controls_dock.isVisible()
        assert window._toggle_controls_act.isChecked() is False

        window._focus_quick_add_input()
        qapp.processEvents()
        assert window.controls_dock.isVisible()
        assert window._toggle_controls_act.isChecked() is True

        window._set_task_table_floating(True)
        qapp.processEvents()
        assert window._is_task_table_floating() is True
        assert window._float_table_act.isChecked() is True
        assert window._floating_table_window is not None
        assert window._floating_table_window.isVisible() is True
        assert window._table_placeholder.isVisible() is False
        assert window.centralWidget().isVisible() is False

        assert window.model.add_task_with_values("Parent A")
        parent_a = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A1", parent_id=parent_a)
        child_a1 = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A2", parent_id=parent_a)
        child_a2 = int(window.model.last_added_task_id())

        assert window.model.add_task_with_values("Parent B")
        parent_b = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child B1", parent_id=parent_b)
        child_b1 = int(window.model.last_added_task_id())

        window._focus_task_by_id(parent_a)
        window._refresh_task_browser()
        qapp.processEvents()

        assert window.details_panel.parent_jump.count() == 2
        assert window._is_task_table_visible() is True

        window.controls_dock.hide()
        qapp.processEvents()
        assert not window.controls_dock.isVisible()
        assert window._is_task_table_visible() is True

        window._set_tree_visible(False, show_message=False)
        qapp.processEvents()
        assert window._is_task_table_visible() is False
        assert window._toggle_table_act.isChecked() is False
        assert window.details_panel.toggle_table_btn.text() == "Show table"
        assert not window.controls_dock.isVisible()
        assert window.centralWidget().isVisible() is False

        window._navigate_child_relative(1)
        qapp.processEvents()
        assert window._selected_task_id() == child_a1

        window._navigate_child_relative(1)
        qapp.processEvents()
        assert window._selected_task_id() == child_a2

        window._navigate_parent_relative(1)
        qapp.processEvents()
        assert window._selected_task_id() == parent_b

        jump_index = window.details_panel.parent_jump.findData(parent_a)
        assert jump_index >= 0
        window.details_panel.parent_jump.setCurrentIndex(jump_index)
        qapp.processEvents()
        assert window._selected_task_id() == parent_a

        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert window._is_task_table_visible() is True
        assert window._toggle_table_act.isChecked() is True
        assert window.details_panel.toggle_table_btn.text() == "Hide table"
        assert window.centralWidget().isVisible() is False

        window._set_task_table_floating(False)
        qapp.processEvents()
        assert window._is_task_table_floating() is False
        assert window._float_table_act.isChecked() is False
        assert window._table_placeholder.isVisible() is False
        assert window._is_task_table_visible() is True
        assert window.centralWidget().isVisible() is True

        window._focus_search_input()
        qapp.processEvents()
        assert window.controls_dock.isVisible()
        assert window._toggle_controls_act.isChecked() is True

        window._focus_task_by_id(child_b1)
        qapp.processEvents()
        assert window._selected_task_id() == child_b1
    finally:
        window.close()
        qapp.processEvents()


def test_refresh_views_after_db_close_does_not_crash(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project Root")
        task_id = int(window.model.last_added_task_id())
        window._focus_task_by_id(task_id)
        qapp.processEvents()

        window.db.close()
        window._refresh_active_task_views()
        window._refresh_focus_panel()
        window._refresh_review_panel()
        window._refresh_analytics_panel()
        window._refresh_calendar_list()
        window._refresh_calendar_markers()
        qapp.processEvents()

        assert window._active_task_id is None
        assert window.project_panel._current_project_id is None
        assert window.relationships_panel.active_task_label.text() == "No task selected"
    finally:
        window._closing_down = True
        if getattr(window.db, "conn", None) is not None:
            window.db.close()
        window.close()
        qapp.processEvents()


def test_task_header_repairs_tiny_saved_section_widths(tmp_path, qapp, monkeypatch):
    seed_window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        header = seed_window.view.header()
        for logical in range(min(4, seed_window.proxy.columnCount())):
            if not seed_window.view.isColumnHidden(logical):
                header.resizeSection(logical, 24)
        QSettings().setValue("ui/header_state", header.saveState())
        QSettings().sync()
    finally:
        seed_window.close()
        qapp.processEvents()

    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        header = window.view.header()
        for logical in range(min(4, window.proxy.columnCount())):
            if window.view.isColumnHidden(logical):
                continue
            assert (
                header.sectionSize(logical)
                >= window._minimum_header_width_for_column(logical)
            )
    finally:
        window.close()
        qapp.processEvents()


def test_semantic_row_coloring_is_limited_to_first_visible_cell(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Color Test", due_date="2026-03-07")
        task_id = int(window.model.last_added_task_id())
        window._focus_task_by_id(task_id)
        qapp.processEvents()

        delegate = window.view.itemDelegate()
        idx_desc = window.proxy.index(0, 0)
        idx_due = window.proxy.index(0, 1)
        def _paint_cell(index):
            image = QImage(180, 42, QImage.Format.Format_ARGB32)
            image.fill(window.view.palette().base().color())
            option = QStyleOptionViewItem()
            option.widget = window.view
            option.rect = image.rect()
            option.state = QStyle.StateFlag.State_Enabled
            painter = QPainter(image)
            delegate.paint(painter, option, index)
            painter.end()
            return image

        desc_img = _paint_cell(idx_desc)
        due_img = _paint_cell(idx_due)

        desc_marker = desc_img.pixelColor(2, 2)
        desc_body = desc_img.pixelColor(60, 21)
        desc_lower = desc_img.pixelColor(2, 21)
        due_marker = due_img.pixelColor(2, 2)
        due_body = due_img.pixelColor(60, 21)

        assert desc_marker != desc_body
        assert desc_lower == desc_body
        assert due_marker == due_body

        header = window.view.header()
        header.moveSection(header.visualIndex(1), 0)
        qapp.processEvents()
        desc_img_reordered = _paint_cell(idx_desc)
        due_img_reordered = _paint_cell(idx_due)

        assert desc_img_reordered.pixelColor(2, 2) == desc_img_reordered.pixelColor(60, 21)
        assert due_img_reordered.pixelColor(2, 2) != due_img_reordered.pixelColor(60, 21)
        assert due_img_reordered.pixelColor(2, 21) == due_img_reordered.pixelColor(60, 21)
    finally:
        window.close()
        qapp.processEvents()


def test_task_tree_context_menu_exposes_subtree_parent_context_actions(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project A")
        project_id = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Phase A", parent_id=project_id)
        phase_a = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("A child", parent_id=phase_a)
        assert window.model.add_task_with_values("Phase B", parent_id=project_id)

        window._focus_task_by_id(phase_a)
        qapp.processEvents()

        captured_actions: list[str] = []

        def fake_exec(self, *_args, **_kwargs):
            captured_actions[:] = [action.text() for action in self.actions()]
            return None

        monkeypatch.setattr(QMenu, "exec", fake_exec)

        index = window.view.currentIndex()
        rect = window.view.visualRect(index)
        window._open_context_menu(rect.center())

        assert "Move subtree to previous parent" in captured_actions
        assert "Move subtree to next parent" in captured_actions
        assert "Make subtree independent" in captured_actions
    finally:
        window.close()
        qapp.processEvents()


def test_custom_columns_expand_horizontal_scroll_range_without_manual_resize(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert window.model.add_task_with_values("Scroll Width Test")
        qapp.processEvents()

        initial_max = int(window.view.horizontalScrollBar().maximum())
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
        ):
            window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()

        expected_max = window._expected_task_header_scroll_maximum()
        actual_max = int(window.view.horizontalScrollBar().maximum())

        assert expected_max > initial_max
        assert actual_max == expected_max

        header = window.view.header()
        scrollbar = window.view.horizontalScrollBar()
        last_section = _rightmost_visible_section(window)
        scrollbar.setValue(scrollbar.maximum())
        qapp.processEvents()
        assert (
            header.sectionViewportPosition(last_section)
            + header.sectionSize(last_section)
            <= window.view.viewport().width()
        )

        for logical in range(min(3, window.proxy.columnCount())):
            header.resizeSection(logical, 40)
        qapp.processEvents()

        expected_max = window._expected_task_header_scroll_maximum()
        actual_max = int(window.view.horizontalScrollBar().maximum())
        assert actual_max == expected_max

        last_section = _rightmost_visible_section(window)
        scrollbar.setValue(scrollbar.maximum())
        qapp.processEvents()
        assert (
            header.sectionViewportPosition(last_section)
            + header.sectionSize(last_section)
            <= window.view.viewport().width()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_restored_header_state_keeps_far_right_columns_reachable(
    tmp_path,
    qapp,
    monkeypatch,
):
    seed_window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        seed_window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert seed_window.model.add_task_with_values("Restore Width Test")
        qapp.processEvents()
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
        ):
            seed_window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()

        header = seed_window.view.header()
        for logical in range(min(3, seed_window.proxy.columnCount())):
            header.resizeSection(logical, 48)
        qapp.processEvents()

        QSettings().setValue("ui/header_state", header.saveState())
        QSettings().sync()
    finally:
        seed_window.close()
        qapp.processEvents()

    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()

        expected_max = window._expected_task_header_scroll_maximum()
        actual_max = int(window.view.horizontalScrollBar().maximum())
        assert actual_max == expected_max

        header = window.view.header()
        last_section = _rightmost_visible_section(window)
        window.view.horizontalScrollBar().setValue(window.view.horizontalScrollBar().maximum())
        qapp.processEvents()
        assert (
            header.sectionViewportPosition(last_section)
            + header.sectionSize(last_section)
            <= window.view.viewport().width()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_restored_header_state_disables_stretch_last_section(
    tmp_path,
    qapp,
    monkeypatch,
):
    seed_window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        seed_window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert seed_window.model.add_task_with_values("Stretch Restore Test")
        qapp.processEvents()
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
        ):
            seed_window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()

        header = seed_window.view.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(header.count() - 1, QHeaderView.ResizeMode.Interactive)
        QSettings().setValue("ui/header_state", header.saveState())
        QSettings().sync()
    finally:
        seed_window.close()
        qapp.processEvents()

    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()

        header = window.view.header()
        assert header.stretchLastSection() is False
        assert all(
            header.sectionResizeMode(i) == QHeaderView.ResizeMode.Interactive
            for i in range(header.count())
        )

        window.view.horizontalScrollBar().setValue(window.view.horizontalScrollBar().maximum())
        qapp.processEvents()
        last_section = _rightmost_visible_section(window)
        assert (
            header.sectionViewportPosition(last_section)
            + header.sectionSize(last_section)
            <= window.view.viewport().width()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_columns_menu_lists_custom_columns(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window.model.add_custom_column("Impact score", "text")
        window.model.add_custom_column("Owner rating", "text")
        qapp.processEvents()
        qapp.processEvents()

        window._rebuild_columns_menu()
        action_texts = [a.text() for a in window.m_columns.actions()]

        assert "Add custom column…" in action_texts
        assert "Remove custom column…" in action_texts
        assert "Impact score" in action_texts
        assert "Owner rating" in action_texts
    finally:
        window.close()
        qapp.processEvents()


def test_moved_header_state_keeps_rightmost_visible_column_reachable(
    tmp_path,
    qapp,
    monkeypatch,
):
    seed_window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        seed_window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert seed_window.model.add_task_with_values("Moved Header Test")
        qapp.processEvents()
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
        ):
            seed_window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()

        header = seed_window.view.header()
        visual_last = header.visualIndex(header.count() - 1)
        description_visual = header.visualIndex(0)
        header.moveSection(description_visual, visual_last)
        qapp.processEvents()

        QSettings().setValue("ui/header_state", header.saveState())
        QSettings().sync()
    finally:
        seed_window.close()
        qapp.processEvents()

    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()

        expected_max = window._expected_task_header_scroll_maximum()
        actual_max = int(window.view.horizontalScrollBar().maximum())
        assert actual_max == expected_max

        header = window.view.header()
        rightmost = _rightmost_visible_section(window)
        window.view.horizontalScrollBar().setValue(window.view.horizontalScrollBar().maximum())
        qapp.processEvents()
        assert (
            header.sectionViewportPosition(rightmost)
            + header.sectionSize(rightmost)
            <= window.view.viewport().width()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_showing_rightmost_column_while_scrolled_to_end_keeps_end_visible(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert window.model.add_task_with_values("Show Column Test")
        qapp.processEvents()
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
        ):
            window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()

        header = window.view.header()
        scrollbar = window.view.horizontalScrollBar()
        rightmost = _rightmost_visible_section(window)

        scrollbar.setValue(scrollbar.maximum())
        qapp.processEvents()
        window.view.setColumnHidden(rightmost, True)
        qapp.processEvents()
        qapp.processEvents()

        window.view.setColumnHidden(rightmost, False)
        qapp.processEvents()
        qapp.processEvents()

        rightmost = _rightmost_visible_section(window)
        assert scrollbar.value() == scrollbar.maximum()
        assert (
            header.sectionViewportPosition(rightmost)
            + header.sectionSize(rightmost)
            <= header.viewport().width()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_startup_restore_shows_scrollbar_when_enabled_columns_exceed_viewport(
    tmp_path,
    qapp,
    monkeypatch,
):
    seed_window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        seed_window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert seed_window.model.add_task_with_values("Startup Restore Test")
        qapp.processEvents()
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
            "Extra 3",
        ):
            seed_window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()
        seed_window._save_ui_settings()
    finally:
        seed_window.close()
        qapp.processEvents()

    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        qapp.processEvents()
        qapp.processEvents()
        window._rebuild_columns_menu()
        checked_titles = {
            action.text()
            for action in window.m_columns.actions()
            if action.isCheckable() and action.isChecked()
        }
        visible_titles = {
            str(window.proxy.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole))
            for i in range(window.proxy.columnCount())
            if not window.view.isColumnHidden(i)
        }

        assert checked_titles == visible_titles
        assert window.view.horizontalScrollBar().maximum() == window._expected_task_header_scroll_maximum()
        assert window.view.horizontalScrollBar().maximum() > 0
    finally:
        window.close()
        qapp.processEvents()


def test_stale_builtin_only_header_state_does_not_hide_custom_columns_at_startup(
    tmp_path,
    qapp,
    monkeypatch,
):
    seed_window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        seed_window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        builtin_only_state = seed_window.view.header().saveState()
        builtin_only_keys = [
            seed_window.model.column_key(i)
            for i in range(seed_window.proxy.columnCount())
        ]
        QSettings().setValue("ui/header_state", builtin_only_state)
        QSettings().setValue("ui/header_state_keys", builtin_only_keys)
        QSettings().sync()
    finally:
        seed_window.close()
        qapp.processEvents()

    db = Database(str(tmp_path / "task-browser.sqlite3"))
    try:
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
        ):
            db.add_custom_column(name, "text")
    finally:
        db.close()

    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        qapp.processEvents()
        qapp.processEvents()
        header = window.view.header()
        custom_titles = {"Impact score", "Owner rating", "Risk band", "Client note"}
        live_titles = {
            str(window.proxy.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole))
            for i in range(window.proxy.columnCount())
            if not window.view.isColumnHidden(i)
        }
        assert custom_titles.issubset(live_titles)
        for i in range(window.proxy.columnCount()):
            title = str(window.proxy.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole))
            if title in custom_titles:
                assert header.sectionSize(i) > 0
        assert window.view.horizontalScrollBar().maximum() == window._expected_task_header_scroll_maximum()
    finally:
        window.close()
        qapp.processEvents()


def test_scroll_sync_repairs_oversized_scroll_range_without_manual_resize(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window._set_tree_visible(True, show_message=False)
        qapp.processEvents()
        assert window.model.add_task_with_values("Scroll Range Repair Test")
        qapp.processEvents()
        for name in (
            "Impact score",
            "Owner rating",
            "Risk band",
            "Client note",
            "Region",
            "Stage note",
            "Extra 1",
            "Extra 2",
        ):
            window.model.add_custom_column(name, "text")
        qapp.processEvents()
        qapp.processEvents()

        scrollbar = window.view.horizontalScrollBar()
        expected_max = window._expected_task_header_scroll_maximum()
        scrollbar.setRange(0, expected_max + 200)
        scrollbar.setValue(scrollbar.maximum())
        qapp.processEvents()

        window._flush_task_header_scroll_sync()
        qapp.processEvents()

        assert scrollbar.maximum() == expected_max
        rightmost = _rightmost_visible_section(window)
        header = window.view.header()
        assert (
            header.sectionViewportPosition(rightmost)
            + header.sectionSize(rightmost)
            <= header.viewport().width()
        )
    finally:
        window.close()
        qapp.processEvents()
