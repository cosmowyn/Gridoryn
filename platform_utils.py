from __future__ import annotations

import sys

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication


OS_MACOS = "macos"
OS_WINDOWS = "windows"
OS_LINUX = "linux"
OS_OTHER = "other"


def current_os() -> str:
    plat = sys.platform.lower()
    if plat.startswith("darwin"):
        return OS_MACOS
    if plat.startswith("win"):
        return OS_WINDOWS
    if plat.startswith("linux"):
        return OS_LINUX
    return OS_OTHER


def is_macos() -> bool:
    return current_os() == OS_MACOS


def is_windows() -> bool:
    return current_os() == OS_WINDOWS


def is_linux() -> bool:
    return current_os() == OS_LINUX


def _normalize_shortcut_spec(spec: str, os_name: str | None = None) -> str:
    text = str(spec or "").strip()
    if not text:
        return ""
    active_os = os_name or current_os()
    if active_os == OS_MACOS:
        return (
            text.replace("Command+", "Meta+")
            .replace("Cmd+", "Meta+")
            .replace("Ctrl+", "Meta+")
        )
    return text.replace("Command+", "Ctrl+").replace("Cmd+", "Ctrl+")


def shortcut_sequence(spec: str, os_name: str | None = None) -> QKeySequence:
    return QKeySequence(_normalize_shortcut_spec(spec, os_name=os_name))


def _display_parts_from_spec(spec: str, os_name: str | None = None) -> list[str]:
    text = str(spec or "").strip()
    if not text:
        return []

    active_os = os_name or current_os()
    parts = [part.strip() for part in text.split("+") if part.strip()]
    mapped: list[str] = []
    for part in parts:
        lower = part.lower()
        if lower in {"ctrl", "control"}:
            mapped.append("Command" if active_os == OS_MACOS else "Ctrl")
        elif lower in {"alt", "option"}:
            mapped.append("Option" if active_os == OS_MACOS else "Alt")
        elif lower in {"cmd", "command", "meta"}:
            if active_os == OS_MACOS:
                mapped.append("Command")
            elif active_os == OS_WINDOWS:
                mapped.append("Win")
            else:
                mapped.append("Super")
        elif lower == "shift":
            mapped.append("Shift")
        else:
            mapped.append(part)
    return mapped


def _standard_key_display_text(value: QKeySequence.StandardKey, os_name: str | None = None) -> str:
    active_os = os_name or current_os()
    manual_map = {
        QKeySequence.StandardKey.Undo: "Command+Z" if active_os == OS_MACOS else "Ctrl+Z",
        QKeySequence.StandardKey.Redo: "Command+Shift+Z" if active_os == OS_MACOS else "Ctrl+Shift+Z",
        QKeySequence.StandardKey.Delete: "Delete",
    }
    if value in manual_map:
        return manual_map[value]

    # Only ask Qt for standard-key sequences once the application exists.
    if QApplication.instance() is not None:
        seq = QKeySequence(value)
        text = seq.toString(QKeySequence.SequenceFormat.PortableText)
        if text:
            return shortcut_display_text(text, os_name=active_os)
    return ""


def shortcut_display_text(
    value: str | QKeySequence | QKeySequence.StandardKey,
    os_name: str | None = None,
) -> str:
    if isinstance(value, QKeySequence):
        seq = value
    elif isinstance(value, QKeySequence.StandardKey):
        return _standard_key_display_text(value, os_name=os_name)
    else:
        return "+".join(_display_parts_from_spec(str(value or ""), os_name=os_name))

    text = seq.toString(QKeySequence.SequenceFormat.PortableText)
    if not text:
        return ""

    active_os = os_name or current_os()
    if active_os == OS_MACOS:
        mapping = {
            "Meta": "Command",
            "Alt": "Option",
            "Ctrl": "Control",
        }
    elif active_os == OS_WINDOWS:
        mapping = {"Meta": "Win"}
    else:
        mapping = {"Meta": "Super"}

    parts = [mapping.get(part, part) for part in text.split("+")]
    return "+".join(parts)
