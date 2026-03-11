from __future__ import annotations

from PySide6.QtCore import QSettings

import theme as theme_module
from theme import ThemeManager


def test_theme_manager_prefers_first_existing_bundled_icon(monkeypatch, tmp_path):
    icon_path = tmp_path / "Gridoryn.ico"
    icon_path.write_bytes(b"ico")

    monkeypatch.setattr(theme_module, "_bundled_icon_candidates", lambda: [str(icon_path)])
    manager = ThemeManager(QSettings())
    assert manager._bundled_default_icon_path() == str(icon_path)
