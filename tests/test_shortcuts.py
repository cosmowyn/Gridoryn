from __future__ import annotations

from PySide6.QtCore import QSettings

import main as main_module
from main import MainWindow
from platform_utils import shortcut_display_text
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
        "Shortcut Test",
        db_path=str(tmp_path / "shortcuts.sqlite3"),
        inherit_current_state=False,
    )
    manager.set_current_workspace(str(workspace["id"]))
    window = MainWindow(manager, str(workspace["id"]))
    window.show()
    qapp.processEvents()
    return window


def test_main_window_exposes_coherent_focus_and_toggle_shortcuts(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert shortcut_display_text(window._focus_workspace_act.shortcut()) == shortcut_display_text("Ctrl+1")
        assert shortcut_display_text(window._focus_details_act.shortcut()) == shortcut_display_text("Ctrl+2")
        assert shortcut_display_text(window._focus_filters_act.shortcut()) == shortcut_display_text("Ctrl+3")
        assert shortcut_display_text(window._focus_project_act.shortcut()) == shortcut_display_text("Ctrl+4")
        assert shortcut_display_text(window._focus_relationships_act.shortcut()) == shortcut_display_text("Ctrl+5")
        assert shortcut_display_text(window._focus_focus_mode_act.shortcut()) == shortcut_display_text("Ctrl+6")
        assert shortcut_display_text(window._focus_review_act.shortcut()) == shortcut_display_text("Ctrl+7")
        assert shortcut_display_text(window._focus_calendar_act.shortcut()) == shortcut_display_text("Ctrl+8")
        assert shortcut_display_text(window._focus_analytics_act.shortcut()) == shortcut_display_text("Ctrl+9")
        assert shortcut_display_text(window._focus_undo_history_act.shortcut()) == shortcut_display_text("Ctrl+0")

        project_shortcuts = [
            shortcut_display_text(seq)
            for seq in window._toggle_project_act.shortcuts()
        ]
        focus_shortcuts = [
            shortcut_display_text(seq)
            for seq in window._toggle_focus_act.shortcuts()
        ]
        assert shortcut_display_text("Ctrl+Alt+4") in project_shortcuts
        assert shortcut_display_text("Ctrl+Shift+J") in project_shortcuts
        assert shortcut_display_text("Ctrl+Alt+6") in focus_shortcuts
        assert shortcut_display_text("Ctrl+Shift+F") in focus_shortcuts
    finally:
        window.close()
        qapp.processEvents()


def test_focus_shortcuts_show_hidden_panels_and_move_focus(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        window.details_dock.hide()
        window.project_dock.hide()
        qapp.processEvents()

        window._focus_details_act.trigger()
        qapp.processEvents()

        assert window.details_dock.isVisible()
        assert window.details_panel.notes.hasFocus()

        window._focus_project_act.trigger()
        qapp.processEvents()

        assert window.project_dock.isVisible()
        assert window.project_panel.focus_target().hasFocus()
    finally:
        window.close()
        qapp.processEvents()
