#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_metadata import (
    APP_NAME,
    APP_STORAGE_NAME,
    APP_STORAGE_ORGANIZATION,
    APP_VERSION,
)
from db import Database
from demo_data import LAUNCH_PROJECT_NAME, create_demo_workspace
from main import MainWindow
from workspace_profiles import WorkspaceProfileManager


def _prepare_window(base_dir: Path) -> MainWindow:
    settings = QSettings(
        str(base_dir / "screenshot_settings.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    manager = WorkspaceProfileManager(
        settings=settings,
        base_dir=str(base_dir / "workspaces"),
    )
    result = create_demo_workspace(manager, today=date(2026, 3, 7))
    workspace = result["workspace"]

    window = MainWindow(manager, str(workspace["id"]))
    window.resize(1680, 1020)
    window._set_task_table_floating(False, show_after=True)
    window._set_tree_visible(True, show_message=False)
    window.controls_dock.show()
    window.details_dock.show()
    window.project_dock.show()
    window.relationships_dock.show()
    window.review_dock.hide()
    window.analytics_dock.hide()
    window.calendar_dock.hide()
    window.focus_dock.hide()
    return window


def _focus_description(window: MainWindow, description: str) -> None:
    for row in window.db.fetch_tasks():
        if str(row.get("description") or "") == description:
            window._focus_task_by_id(int(row["id"]))
            break


def _save_widget(widget, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(path))


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication([])
    app.setOrganizationName(APP_STORAGE_ORGANIZATION)
    app.setApplicationName(APP_STORAGE_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    out_dir = PROJECT_ROOT / "docs" / "screenshots"

    with tempfile.TemporaryDirectory(prefix="customtodo_screens_") as tmp_root:
        window = _prepare_window(Path(tmp_root))
        window.show()
        app.processEvents()

        _focus_description(window, "Finalize landing page copy")
        app.processEvents()
        _save_widget(window, out_dir / "main-workspace.png")

        _focus_description(window, LAUNCH_PROJECT_NAME)
        window.project_panel.tabs.setCurrentIndex(4)
        app.processEvents()
        _save_widget(window.project_panel, out_dir / "project-cockpit-timeline.png")

        window.review_dock.show()
        window.project_dock.hide()
        window.details_dock.hide()
        window.relationships_dock.hide()
        app.processEvents()
        _save_widget(window.review_panel, out_dir / "review-workflow.png")

        window.relationships_dock.show()
        _focus_description(window, "Finalize landing page copy")
        app.processEvents()
        _save_widget(window.relationships_panel, out_dir / "relationship-inspector.png")

        window.close()
        app.processEvents()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
