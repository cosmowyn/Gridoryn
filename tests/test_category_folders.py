from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

import main as main_module
from db import Database, MAX_CATEGORY_FOLDER_DEPTH
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
        "Category Folder Test",
        db_path=str(tmp_path / "category-folders.sqlite3"),
        inherit_current_state=False,
    )
    manager.set_current_workspace(str(workspace["id"]))
    window = MainWindow(manager, str(workspace["id"]))
    window.show()
    qapp.processEvents()
    return window


def test_category_folder_depth_limit(tmp_path):
    db = Database(str(tmp_path / "folders.sqlite3"))
    try:
        parent_id = None
        created_ids = []
        for depth in range(MAX_CATEGORY_FOLDER_DEPTH):
            parent_id = db.create_category_folder(f"Folder {depth}", parent_id)
            created_ids.append(parent_id)
        with pytest.raises(ValueError):
            db.create_category_folder("Too deep", parent_id)
        assert len(db.fetch_category_folders()) == MAX_CATEGORY_FOLDER_DEPTH
    finally:
        db.close()


def test_category_folders_group_tree_and_filter_project_cockpit(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window.project_dock.hide()
        qapp.processEvents()

        root_folder_id = window.model.create_category_folder("Operations")
        sub_folder_id = window.model.create_category_folder(
            "Internal",
            parent_folder_id=root_folder_id,
        )

        assert window.model.add_task_with_values(
            "Ops checklist",
            category_folder_id=root_folder_id,
        )
        grouped_task_id = int(window.model.last_added_task_id())

        assert window.model.add_task_with_values(
            "Internal rollout",
            category_folder_id=sub_folder_id,
        )
        nested_grouped_task_id = int(window.model.last_added_task_id())

        assert window.model.add_task_with_values("Loose task")

        folder_node = window.model.folder_node_for_id(root_folder_id)
        assert folder_node is not None
        assert folder_node.folder is not None
        assert folder_node.children

        src_index = window.model._index_for_node(folder_node, 0)
        proxy_index = window.proxy.mapFromSource(src_index)
        window.view.setCurrentIndex(proxy_index)
        window._refresh_active_task_views()
        qapp.processEvents()

        assert window._selected_task_id() is None
        assert window.project_panel.category_combo.currentData() == root_folder_id
        combo_labels = [
            window.project_panel.project_combo.itemText(i)
            for i in range(window.project_panel.project_combo.count())
        ]
        assert any("Ops checklist" in text for text in combo_labels)
        assert any("Internal rollout" in text for text in combo_labels)
        assert all("Loose task" not in text for text in combo_labels)

        window._focus_task_by_id(grouped_task_id)
        qapp.processEvents()
        assert window.project_panel.category_combo.currentData() == root_folder_id

        window._focus_task_by_id(nested_grouped_task_id)
        qapp.processEvents()
        assert window.project_panel.category_combo.currentData() == sub_folder_id
    finally:
        window.close()
        qapp.processEvents()


def test_move_task_with_category_folders_present_does_not_crash(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        root_folder_id = window.model.create_category_folder("Operations")
        assert root_folder_id is not None

        assert window.model.add_task_with_values("Task A")
        task_a_id = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Task B")
        task_b_id = int(window.model.last_added_task_id())

        qapp.processEvents()

        assert window.model.move_task_relative(task_b_id, -1) is True
        qapp.processEvents()

        moved_node = window.model.node_for_id(task_b_id)
        assert moved_node is not None
        assert moved_node.task is not None
        assert int(moved_node.task["sort_order"]) == 1

        other_node = window.model.node_for_id(task_a_id)
        assert other_node is not None
        assert other_node.task is not None
        assert int(other_node.task["sort_order"]) == 2
    finally:
        window.close()
        qapp.processEvents()
