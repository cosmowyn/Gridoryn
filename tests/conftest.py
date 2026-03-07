from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    settings_root = tmp_path_factory.mktemp("qt_settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root))
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("FocusToolsTest")
    app.setApplicationName("CustomTaskManagerTest")
    return app


@pytest.fixture(autouse=True)
def _clear_default_settings(qapp):
    settings = QSettings()
    settings.clear()
    settings.sync()
    yield
