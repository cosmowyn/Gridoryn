from __future__ import annotations

from PySide6.QtCore import QSettings

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
        assert window._table_placeholder.isVisible() is True

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

        window._set_task_table_floating(False)
        qapp.processEvents()
        assert window._is_task_table_floating() is False
        assert window._float_table_act.isChecked() is False
        assert window._table_placeholder.isVisible() is False
        assert window._is_task_table_visible() is True

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
