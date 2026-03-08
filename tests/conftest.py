from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    settings_root = tmp_path_factory.mktemp("qt_settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root))
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("CustomToDoTest")
    app.setApplicationName("CustomToDoTest")
    app.setApplicationDisplayName("CustomToDoTest")
    return app


@pytest.fixture(autouse=True)
def _clear_default_settings(qapp):
    settings = QSettings()
    settings.clear()
    settings.sync()
    yield
