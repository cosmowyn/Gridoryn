from __future__ import annotations

from PySide6.QtGui import QKeySequence

from platform_utils import (
    OS_LINUX,
    OS_MACOS,
    OS_WINDOWS,
    shortcut_display_text,
    shortcut_sequence,
)


def test_shortcut_sequence_uses_command_on_macos():
    seq = shortcut_sequence("Ctrl+Shift+P", os_name=OS_MACOS)
    assert shortcut_display_text(seq, os_name=OS_MACOS) == "Command+Shift+P"


def test_shortcut_sequence_keeps_ctrl_on_windows():
    seq = shortcut_sequence("Ctrl+Alt+Space", os_name=OS_WINDOWS)
    assert shortcut_display_text(seq, os_name=OS_WINDOWS) == "Ctrl+Alt+Space"


def test_shortcut_display_uses_option_label_on_macos():
    assert shortcut_display_text("Ctrl+Alt+Up", os_name=OS_MACOS) == "Command+Option+Up"


def test_shortcut_display_uses_super_label_on_linux_for_meta():
    assert shortcut_display_text("Meta+L", os_name=OS_LINUX) == "Super+L"


def test_standard_key_display_text_is_safe_without_qapplication():
    assert shortcut_display_text(QKeySequence.StandardKey.Undo, os_name=OS_MACOS) == "Command+Z"
