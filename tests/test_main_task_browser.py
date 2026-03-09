from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

import main as main_module
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

        desc_strip = desc_img.pixelColor(2, 21)
        desc_body = desc_img.pixelColor(60, 21)
        due_strip = due_img.pixelColor(2, 21)
        due_body = due_img.pixelColor(60, 21)

        assert desc_strip != desc_body
        assert due_strip == due_body

        header = window.view.header()
        header.moveSection(header.visualIndex(1), 0)
        qapp.processEvents()
        desc_img_reordered = _paint_cell(idx_desc)
        due_img_reordered = _paint_cell(idx_due)

        assert desc_img_reordered.pixelColor(2, 21) == desc_img_reordered.pixelColor(60, 21)
        assert due_img_reordered.pixelColor(2, 21) != due_img_reordered.pixelColor(60, 21)
    finally:
        window.close()
        qapp.processEvents()
