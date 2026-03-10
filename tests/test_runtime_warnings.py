from __future__ import annotations

from PySide6.QtCore import QRect, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QStyleOptionViewItem, QTreeView

import main as main_module
from db import Database
from delegates import SmartDelegate
from main import MainWindow
from model import TaskTreeModel
from workspace_profiles import WorkspaceProfileManager


def _workspace_manager(tmp_path):
    manager = WorkspaceProfileManager(base_dir=str(tmp_path / "workspace-data"))
    workspace = manager.create_workspace(
        "Runtime Warnings Test",
        db_path=str(tmp_path / "runtime-warnings.sqlite3"),
        inherit_current_state=False,
    )
    manager.set_current_workspace(str(workspace["id"]))
    return manager, str(workspace["id"])


def test_main_window_skips_tray_when_no_icon_is_available(tmp_path, qapp, monkeypatch):
    QSettings().setValue("ui/onboarding_completed", True)

    class FakeTrayIcon:
        created = False

        @staticmethod
        def isSystemTrayAvailable():
            return True

        def __init__(self, *_args, **_kwargs):
            FakeTrayIcon.created = True

    monkeypatch.setattr(main_module, "QSystemTrayIcon", FakeTrayIcon)
    monkeypatch.setattr(MainWindow, "_install_optional_global_capture_hotkey", lambda self: None)
    monkeypatch.setattr(MainWindow, "_resolved_tray_icon", lambda self: None)

    manager, workspace_id = _workspace_manager(tmp_path)
    window = MainWindow(manager, workspace_id)
    try:
        assert FakeTrayIcon.created is False
        assert window._tray_icon is None
    finally:
        window.close()
        qapp.processEvents()


def test_main_window_resolved_tray_icon_uses_qstyle_fallback(tmp_path, qapp, monkeypatch):
    QSettings().setValue("ui/onboarding_completed", True)
    monkeypatch.setattr(main_module.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    monkeypatch.setattr(MainWindow, "_install_optional_global_capture_hotkey", lambda self: None)

    manager, workspace_id = _workspace_manager(tmp_path)
    window = MainWindow(manager, workspace_id)
    try:
        window.setWindowIcon(QIcon())
        window.model.current_window_icon = lambda: QIcon()
        icon = window._resolved_tray_icon()
        assert icon is not None
        assert icon.isNull() is False
    finally:
        window.close()
        qapp.processEvents()


def test_delegate_ignores_stale_editor_when_active_root_changes(tmp_path, qapp):
    db = Database(str(tmp_path / "delegate-owner.sqlite3"))
    db.insert_task({"description": "Alpha", "sort_order": 1})
    view = QTreeView()
    model = TaskTreeModel(db)
    view.setModel(model)

    delegate = SmartDelegate(view)
    view.setItemDelegate(delegate)
    view.show()
    qapp.processEvents()

    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 160, 36)
    option.fontMetrics = view.fontMetrics()
    index = model.index(0, 0)

    emitted: list[tuple[str, object]] = []
    delegate.commitData.connect(lambda editor: emitted.append(("commit", editor)))
    delegate.closeEditor.connect(lambda editor, *_args: emitted.append(("close", editor)))

    editor_one = delegate.createEditor(view.viewport(), option, index)
    editor_two = delegate.createEditor(view.viewport(), option, index)

    delegate._commit_and_close_editor(editor_one)
    qapp.processEvents()
    assert emitted == []

    delegate._commit_and_close_editor(editor_two)
    qapp.processEvents()
    assert [name for name, _editor in emitted] == ["commit", "close"]
