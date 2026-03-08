from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QListWidget

import main as main_module
from main import MainWindow
from workspace_profiles import WorkspaceProfileManager


def _build_window(tmp_path, qapp, monkeypatch):
    QSettings().setValue("ui/onboarding_completed", True)
    monkeypatch.setattr(
        main_module.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: False),
    )
    monkeypatch.setattr(
        MainWindow,
        "_install_optional_global_capture_hotkey",
        lambda self: None,
    )
    manager = WorkspaceProfileManager(base_dir=str(tmp_path / "workspace-data"))
    workspace = manager.create_workspace(
        "Selection Sync Test",
        db_path=str(tmp_path / "selection-sync.sqlite3"),
        inherit_current_state=False,
    )
    manager.set_current_workspace(str(workspace["id"]))
    window = MainWindow(manager, str(workspace["id"]))
    window.show()
    qapp.processEvents()
    return window


def test_active_task_selection_stays_synchronized_across_views(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project A")
        parent_id = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A1", parent_id=parent_id)
        child_one = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A2", parent_id=parent_id)
        child_two = int(window.model.last_added_task_id())

        window.relationships_dock.show()
        window.focus_dock.show()
        qapp.processEvents()

        window._focus_task_by_id(child_one)
        qapp.processEvents()
        assert window.relationships_panel.active_task_label.text() == "Child A1"
        assert "Status:" in window.relationships_panel.meta_label.text()
        assert window.relationships_panel.active_task_label.font().bold()
        assert "Child A1" in window.focus_panel.current_task.text()
        assert "Child A1" in window._active_task_label.text()
        assert window.details_panel.task_id() == child_one

        window._focus_task_by_id(child_two)
        qapp.processEvents()
        assert window.relationships_panel.active_task_label.text() == "Child A2"
        assert "Child A2" in window.focus_panel.current_task.text()
        assert "Child A2" in window._active_task_label.text()
        assert window.details_panel.task_id() == child_two
    finally:
        window.close()
        qapp.processEvents()


def test_relationship_inspector_navigation_updates_main_selection(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project A")
        parent_id = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A1", parent_id=parent_id)
        child_one = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A2", parent_id=parent_id)
        child_two = int(window.model.last_added_task_id())

        window.relationships_dock.show()
        window._focus_task_by_id(child_two)
        qapp.processEvents()

        window.relationships_panel.tabs.setCurrentIndex(1)
        qapp.processEvents()

        sibling_list = window.relationships_panel.findChild(
            QListWidget,
            "RelationshipsList_siblings",
        )
        assert sibling_list is not None
        assert sibling_list.count() >= 1
        sibling_list.setCurrentRow(0)
        sibling_list.setFocus()
        window.relationships_panel.focus_btn.click()
        qapp.processEvents()

        assert window._selected_task_id() == child_one
        assert window.details_panel.task_id() == child_one
        assert window.relationships_panel.active_task_label.text() == "Child A1"
    finally:
        window.close()
        qapp.processEvents()
