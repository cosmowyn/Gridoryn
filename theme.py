from __future__ import annotations

import json
import os
import sys
from copy import deepcopy

from PySide6.QtGui import QFont, QIcon, QColor, QPalette
from PySide6.QtWidgets import QApplication

from app_metadata import APP_NAME
from app_paths import resource_path


DEFAULT_THEME_NAME = "Light"


def _bundled_icon_candidates() -> list[str]:
    base_candidates = [
        resource_path("build_assets", "icons", f"{APP_NAME}.png"),
        resource_path("icon.png"),
    ]
    if os.name == "nt":
        return [
            resource_path("build_assets", "icons", f"{APP_NAME}.ico"),
            resource_path("icon.ico"),
            *base_candidates,
        ]
    if sys.platform == "darwin":
        return [
            resource_path("build_assets", "icons", f"{APP_NAME}.icns"),
            *base_candidates,
        ]
    return [
        resource_path("build_assets", "icons", f"{APP_NAME}.png"),
        resource_path("build_assets", "icons", f"{APP_NAME}.ico"),
        resource_path("icon.png"),
        resource_path("icon.ico"),
    ]


def _font_to_str(font: QFont) -> str:
    return font.toString()


def _font_from_str(s: str, fallback: QFont) -> QFont:
    f = QFont(fallback)
    if isinstance(s, str) and s:
        ok = f.fromString(s)
        if ok:
            return f
    return QFont(fallback)


def _font_css(font: QFont) -> str:
    fam = font.family().replace("'", "\\'")
    size = font.pointSize()
    if size <= 0:
        size = 10
    weight = font.weight()
    italic = "italic" if font.italic() else "normal"
    return f"font-family: '{fam}'; font-size: {size}pt; font-weight: {weight}; font-style: {italic};"


def _qcolor_to_hex(c: QColor, fallback: str) -> str:
    if not isinstance(c, QColor) or not c.isValid():
        return fallback
    return c.name()


def _rgba(qcolor: QColor, alpha: float) -> str:
    if not isinstance(qcolor, QColor) or not qcolor.isValid():
        return "rgba(0,0,0,0)"
    a = max(0.0, min(1.0, float(alpha)))
    return f"rgba({qcolor.red()},{qcolor.green()},{qcolor.blue()},{a:.3f})"


def _ensure_contrast(bg_hex: str, fg_hex: str) -> str:
    try:
        bg = QColor(bg_hex)
        fg = QColor(fg_hex)
        if not bg.isValid() or not fg.isValid():
            return fg_hex

        lum_bg = 0.2126 * bg.red() + 0.7152 * bg.green() + 0.0722 * bg.blue()
        lum_fg = 0.2126 * fg.red() + 0.7152 * fg.green() + 0.0722 * fg.blue()

        if abs(lum_bg - lum_fg) >= 120:
            return fg_hex

        return "#000000" if lum_bg > 150 else "#FFFFFF"
    except Exception:
        return fg_hex


def _default_border_side(enabled: bool, width: float, color: str, style: str) -> dict:
    return {
        "enabled": bool(enabled),
        "width": float(width),
        "color": str(color),
        "style": str(style),
    }


def _default_borders(colors: dict) -> dict:
    return {
        "headers": {
            "top": _default_border_side(True, 1, colors["header_border"], "solid"),
            "right": _default_border_side(True, 1, colors["header_border"], "solid"),
            "bottom": _default_border_side(True, 1, colors["header_border"], "solid"),
            "left": _default_border_side(True, 1, colors["header_border"], "solid"),
        },
        "cells": {
            "top": _default_border_side(False, 0, colors["grid"], "solid"),
            "right": _default_border_side(False, 0, colors["grid"], "solid"),
            "bottom": _default_border_side(False, 0, colors["grid"], "solid"),
            "left": _default_border_side(False, 0, colors["grid"], "solid"),
        },
        "siblings": {
            "top": _default_border_side(False, 0, colors["grid"], "solid"),
            "right": _default_border_side(False, 0, colors["grid"], "solid"),
            "bottom": _default_border_side(True, 1, colors["grid"], "solid"),
            "left": _default_border_side(False, 0, colors["grid"], "solid"),
        },
    }


def _system_palette_colors() -> dict:
    app = QApplication.instance()
    pal = app.palette() if app else QPalette()

    window_bg = _qcolor_to_hex(pal.color(QPalette.ColorRole.Window), "#F5F5F5")
    window_fg = _qcolor_to_hex(pal.color(QPalette.ColorRole.WindowText), "#111111")
    base_bg = _qcolor_to_hex(pal.color(QPalette.ColorRole.Base), "#FFFFFF")
    text_fg = _qcolor_to_hex(pal.color(QPalette.ColorRole.Text), "#111111")

    sel_bg = _qcolor_to_hex(pal.color(QPalette.ColorRole.Highlight), "#2B6DE0")
    sel_fg = _qcolor_to_hex(pal.color(QPalette.ColorRole.HighlightedText), "#FFFFFF")

    btn_bg = _qcolor_to_hex(pal.color(QPalette.ColorRole.Button), "#EDEDED")
    btn_fg = _qcolor_to_hex(pal.color(QPalette.ColorRole.ButtonText), "#111111")

    placeholder_fg = _qcolor_to_hex(pal.color(QPalette.ColorRole.PlaceholderText), "#666666")

    mid = pal.color(QPalette.ColorRole.Mid)
    mid_hex = _qcolor_to_hex(mid, "#C9C9C9")

    window_fg = _ensure_contrast(window_bg, window_fg)
    text_fg = _ensure_contrast(base_bg, text_fg)
    btn_fg = _ensure_contrast(btn_bg, btn_fg)
    sel_fg = _ensure_contrast(sel_bg, sel_fg)

    btn_disabled_fg = _ensure_contrast(
        btn_bg,
        _qcolor_to_hex(
            pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText),
            "#888888",
        ),
    )

    header_bg = _rgba(QColor("#000000"), 0.04)
    tree_alt_bg = _rgba(QColor("#000000"), 0.02)

    return {
        "window_bg": window_bg,
        "window_fg": window_fg,

        "menubar_bg": window_bg,
        "menu_bg": base_bg,
        "menu_fg": text_fg,
        "menu_border": mid_hex,

        "toolbar_bg": window_bg,
        "toolbar_border": mid_hex,

        "tree_bg": base_bg,
        "tree_alt_bg": tree_alt_bg,
        "tree_fg": text_fg,
        "grid": mid_hex,

        "header_bg": header_bg,
        "header_fg": text_fg,
        "header_border": mid_hex,

        "sel_bg": sel_bg,
        "sel_fg": sel_fg,

        "btn_bg": btn_bg,
        "btn_fg": btn_fg,
        "btn_border": mid_hex,
        "btn_hover_bg": _rgba(QColor("#000000"), 0.06),
        "btn_pressed_bg": _rgba(QColor("#000000"), 0.10),
        "btn_disabled_bg": _rgba(QColor("#000000"), 0.03),
        "btn_disabled_fg": btn_disabled_fg,

        "input_bg": base_bg,
        "input_fg": text_fg,
        "input_border": mid_hex,
        "input_focus_border": sel_bg,

        "search_bg": base_bg,
        "search_fg": text_fg,
        "search_border": mid_hex,
        "search_focus_border": sel_bg,
        "search_placeholder_fg": placeholder_fg,

        "search_clear_bg": btn_bg,
        "search_clear_fg": btn_fg,
        "search_clear_border": mid_hex,
        "search_clear_hover_bg": _rgba(QColor("#000000"), 0.06),
        "search_clear_pressed_bg": _rgba(QColor("#000000"), 0.10),

        "row_add_bg": "#E7F6EC",
        "row_add_fg": _ensure_contrast("#E7F6EC", "#0D3B1E"),
        "row_add_border": "#9ED7AF",
        "row_add_hover_bg": "#D6F0DE",
        "row_add_pressed_bg": "#BFE8CD",

        "row_del_bg": "#FCEAEA",
        "row_del_fg": _ensure_contrast("#FCEAEA", "#5A0E0E"),
        "row_del_border": "#F0B4B4",
        "row_del_hover_bg": "#FADADA",
        "row_del_pressed_bg": "#F6C4C4",

        "gantt_task_bg": "#2563EB",
        "gantt_task_text": _ensure_contrast("#2563EB", "#F9FAFB"),
        "gantt_summary_bg": "#1F2937",
        "gantt_summary_text": _ensure_contrast("#1F2937", "#F9FAFB"),

        "clock_face_bg": base_bg,
        "clock_face_border": mid_hex,
        "clock_text": text_fg,
        "clock_tick": mid_hex,
        "clock_hand": sel_bg,
        "clock_accent": sel_bg,
        "clock_accent_text": sel_fg,
        "clock_center_dot": sel_bg,
    }


def light_theme_dict() -> dict:
    base_font = QFont()
    if base_font.pointSize() <= 0:
        base_font.setPointSize(10)

    colors = _system_palette_colors()

    return {
        "name": "Light",
        "app_icon_path": "",
        "fonts": {
            "base": _font_to_str(base_font),
            "header": _font_to_str(QFont(base_font.family(), base_font.pointSize(), QFont.Weight.DemiBold)),
            "tree": _font_to_str(base_font),
            "button": _font_to_str(QFont(base_font.family(), base_font.pointSize(), QFont.Weight.Medium)),
            "input": _font_to_str(base_font),
            "menu": _font_to_str(base_font),
            "search": _font_to_str(QFont(base_font.family(), base_font.pointSize(), QFont.Weight.Medium)),
        },
        "colors": colors,
        "borders": _default_borders(colors),
        "task_status_indicator": {
            "shape": "bar",
            "size": 10,
            "width": 10,
        },
        "custom_qss": "",
    }


def default_theme_dict() -> dict:
    return light_theme_dict()


class ThemeManager:
    def __init__(self, settings):
        self.settings = settings
        self.ensure_defaults()

    def ensure_defaults(self):
        names = self.list_themes()

        if not names:
            t = light_theme_dict()
            self.save_theme(DEFAULT_THEME_NAME, t)
            self.set_current_theme(DEFAULT_THEME_NAME)
            return

        if "Light" not in names:
            self.save_theme("Light", light_theme_dict())

        cur = self.current_theme_name()
        if cur not in self.list_themes():
            self.set_current_theme("Light" if "Light" in self.list_themes() else self.list_themes()[0])

    def list_themes(self) -> list[str]:
        v = self.settings.value("themes/list", [])
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v]
        return []

    def current_theme_name(self) -> str:
        name = self.settings.value("themes/current", DEFAULT_THEME_NAME)
        return str(name) if name else DEFAULT_THEME_NAME

    def set_current_theme(self, name: str):
        self.settings.setValue("themes/current", name)

    def load_theme(self, name: str) -> dict:
        raw = self.settings.value(f"themes/data/{name}")
        if not raw:
            t = default_theme_dict()
            t["name"] = name
            return t

        try:
            t = json.loads(str(raw))
        except Exception:
            t = default_theme_dict()
            t["name"] = name

        d = default_theme_dict()
        out = deepcopy(d)
        out["name"] = name

        out["app_icon_path"] = t.get("app_icon_path", out["app_icon_path"])
        out["custom_qss"] = t.get("custom_qss", out["custom_qss"])
        out_indicator = out.get("task_status_indicator", {})
        t_indicator = (
            t.get("task_status_indicator", {})
            if isinstance(t.get("task_status_indicator", {}), dict)
            else {}
        )
        out_indicator.update(t_indicator)
        out["task_status_indicator"] = out_indicator

        out_fonts = out.get("fonts", {})
        t_fonts = t.get("fonts", {}) if isinstance(t.get("fonts", {}), dict) else {}
        out_fonts.update(t_fonts)
        out["fonts"] = out_fonts

        out_colors = out.get("colors", {})
        t_colors = t.get("colors", {}) if isinstance(t.get("colors", {}), dict) else {}
        out_colors.update(t_colors)
        out["colors"] = out_colors

        out_borders = out.get("borders", {})
        t_borders = t.get("borders", {}) if isinstance(t.get("borders", {}), dict) else {}
        for section in ("headers", "cells", "siblings"):
            out_section = out_borders.get(section, {})
            t_section = t_borders.get(section, {}) if isinstance(t_borders.get(section, {}), dict) else {}
            for side in ("top", "right", "bottom", "left"):
                out_side = out_section.get(side, {})
                t_side = t_section.get(side, {}) if isinstance(t_section.get(side, {}), dict) else {}
                if isinstance(out_side, dict):
                    out_side.update(t_side)
                    out_section[side] = out_side
            out_borders[section] = out_section
        out["borders"] = out_borders

        return out

    def save_theme(self, name: str, theme: dict):
        names = self.list_themes()
        if name not in names:
            names.append(name)
            self.settings.setValue("themes/list", names)

        payload = deepcopy(theme)
        payload["name"] = name
        self.settings.setValue(f"themes/data/{name}", json.dumps(payload, ensure_ascii=False))

    def delete_theme(self, name: str):
        names = self.list_themes()
        if name not in names or len(names) == 1:
            return

        names = [n for n in names if n != name]
        self.settings.setValue("themes/list", names)
        self.settings.remove(f"themes/data/{name}")

        if self.current_theme_name() == name:
            self.set_current_theme(names[0])

    def duplicate_theme(self, source_name: str, new_name: str):
        t = self.load_theme(source_name)
        t["name"] = new_name
        self.save_theme(new_name, t)

    def _bundled_default_icon_path(self) -> str:
        for candidate in _bundled_icon_candidates():
            if os.path.isfile(candidate):
                return candidate
        return ""

    def icon_for_theme(self, theme: dict) -> QIcon | None:
        path = str(theme.get("app_icon_path") or "").strip()
        if not path:
            path = self._bundled_default_icon_path()
        if not os.path.isfile(path):
            return None
        ico = QIcon(path)
        return ico if not ico.isNull() else None

    def _css_border_side(self, side_cfg: dict) -> str:
        enabled = bool(side_cfg.get("enabled", False))
        width = float(side_cfg.get("width", 0))
        color = str(side_cfg.get("color", "#000000"))
        style = str(side_cfg.get("style", "solid"))

        if not enabled or width <= 0:
            return "0px none transparent"
        width_text = f"{width:.2f}".rstrip("0").rstrip(".")
        return f"{width_text}px {style} {color}"

    def _build_stylesheet(self, theme: dict) -> str:
        c = theme["colors"]
        b = theme.get("borders", {})

        hb = b.get("headers", {})

        base_font = _font_from_str(theme["fonts"].get("base", ""), QFont())
        header_font = _font_from_str(theme["fonts"].get("header", ""), base_font)
        tree_font = _font_from_str(theme["fonts"].get("tree", ""), base_font)
        button_font = _font_from_str(theme["fonts"].get("button", ""), base_font)
        input_font = _font_from_str(theme["fonts"].get("input", ""), base_font)
        menu_font = _font_from_str(theme["fonts"].get("menu", ""), base_font)
        search_font = _font_from_str(theme["fonts"].get("search", ""), input_font)

        qss = f"""
        QMainWindow {{ background: {c["window_bg"]}; color: {c["window_fg"]}; }}
        QWidget {{ color: {c["window_fg"]}; }}

        QMenuBar {{
            background: {c["menubar_bg"]}; color: {c["menu_fg"]};
            {_font_css(menu_font)}
        }}
        QMenuBar::item:selected {{ background: {c["sel_bg"]}; color: {c["sel_fg"]}; }}
        QMenu {{
            background: {c["menu_bg"]}; color: {c["menu_fg"]};
            border: 1px solid {c["menu_border"]};
            {_font_css(menu_font)}
        }}
        QMenu::item:selected {{ background: {c["sel_bg"]}; color: {c["sel_fg"]}; }}

        QToolBar {{ background: {c["toolbar_bg"]}; border-bottom: 1px solid {c["toolbar_border"]}; }}

        QTreeView {{
            background: {c["tree_bg"]};
            alternate-background-color: {c["tree_alt_bg"]};
            color: {c["tree_fg"]};
            gridline-color: {c["grid"]};
            selection-background-color: {c["sel_bg"]};
            selection-color: {c["sel_fg"]};
            border: 1px solid {c["input_border"]};
            {_font_css(tree_font)}
        }}
        QTreeView:focus {{
            border: 1px solid {c["input_focus_border"]};
        }}

        QHeaderView::section {{
            background: {c["header_bg"]};
            color: {c["header_fg"]};
            border-top: {self._css_border_side(hb.get("top", {}))};
            border-right: {self._css_border_side(hb.get("right", {}))};
            border-bottom: {self._css_border_side(hb.get("bottom", {}))};
            border-left: {self._css_border_side(hb.get("left", {}))};
            padding: 6px;
            {_font_css(header_font)}
        }}

        QPushButton {{
            background: {c["btn_bg"]}; color: {c["btn_fg"]};
            border: 1px solid {c["btn_border"]};
            padding: 7px 12px; border-radius: 6px;
            {_font_css(button_font)}
        }}
        QPushButton:hover {{ background: {c["btn_hover_bg"]}; }}
        QPushButton:pressed {{ background: {c["btn_pressed_bg"]}; }}
        QPushButton:focus, QToolButton:focus {{
            border: 1px solid {c["input_focus_border"]};
        }}
        QPushButton:disabled {{
            background: {c["btn_disabled_bg"]}; color: {c["btn_disabled_fg"]};
            border-color: {c["btn_disabled_bg"]};
        }}

        QLineEdit, QComboBox, QSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
            background: {c["input_bg"]}; color: {c["input_fg"]};
            border: 1px solid {c["input_border"]};
            padding: 6px; border-radius: 6px;
            selection-background-color: {c["sel_bg"]};
            selection-color: {c["sel_fg"]};
            {_font_css(input_font)}
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
            border: 1px solid {c["input_focus_border"]};
        }}

        QLineEdit#SearchBar {{
            background: {c["search_bg"]};
            color: {c["search_fg"]};
            border: 1px solid {c["search_border"]};
            padding: 7px 10px;
            border-radius: 10px;
            {_font_css(search_font)}
        }}
        QLineEdit#SearchBar:focus {{ border: 1px solid {c["search_focus_border"]}; }}

        QListWidget, QUndoView, QTextBrowser {{
            border: 1px solid {c["input_border"]};
            border-radius: 6px;
        }}
        QListWidget:focus, QUndoView:focus, QTextBrowser:focus {{
            border: 1px solid {c["input_focus_border"]};
        }}

        QToolButton#SearchClear {{
            background: {c["search_clear_bg"]};
            color: {c["search_clear_fg"]};
            border: 1px solid {c["search_clear_border"]};
            padding: 6px 10px;
            border-radius: 10px;
        }}
        QToolButton#SearchClear:hover {{ background: {c["search_clear_hover_bg"]}; }}
        QToolButton#SearchClear:pressed {{ background: {c["search_clear_pressed_bg"]}; }}

        QToolButton#RowAddChildButton {{
            background: {c["row_add_bg"]};
            color: {c["row_add_fg"]};
            border: 1px solid {c["row_add_border"]};
            border-radius: 8px;
            padding: 0px;
            {_font_css(button_font)}
            font-weight: 700;
        }}
        QToolButton#RowAddChildButton:hover {{ background: {c["row_add_hover_bg"]}; }}
        QToolButton#RowAddChildButton:pressed {{ background: {c["row_add_pressed_bg"]}; }}

        QToolButton#RowDeleteButton {{
            background: {c["row_del_bg"]};
            color: {c["row_del_fg"]};
            border: 1px solid {c["row_del_border"]};
            border-radius: 8px;
            padding: 0px;
            {_font_css(button_font)}
            font-weight: 700;
        }}
        QToolButton#RowDeleteButton:hover {{ background: {c["row_del_hover_bg"]}; }}
        QToolButton#RowDeleteButton:pressed {{ background: {c["row_del_pressed_bg"]}; }}

        QToolButton#PerspectiveNavButton {{
            background: {c["btn_bg"]};
            color: {c["btn_fg"]};
            border: 1px solid {c["btn_border"]};
            border-radius: 10px;
            padding: 6px 12px;
            {_font_css(button_font)}
        }}
        QToolButton#PerspectiveNavButton:hover {{ background: {c["btn_hover_bg"]}; }}
        QToolButton#PerspectiveNavButton:pressed {{ background: {c["btn_pressed_bg"]}; }}
        QToolButton#PerspectiveNavButton:checked {{
            background: {c["sel_bg"]};
            color: {c["sel_fg"]};
            border: 1px solid {c["input_focus_border"]};
            font-weight: 600;
        }}
        QToolButton#PerspectiveNavButton:checked:hover {{ background: {c["sel_bg"]}; }}

        QToolButton#ContextHelpButton {{
            background: {c["btn_bg"]};
            color: {c["btn_fg"]};
            border: 1px solid {c["btn_border"]};
            border-radius: 12px;
            padding: 0px;
            min-width: 24px;
            max-width: 24px;
            min-height: 24px;
            max-height: 24px;
            {_font_css(button_font)}
            font-weight: 700;
        }}
        QToolButton#ContextHelpButton:hover {{ background: {c["btn_hover_bg"]}; }}
        QToolButton#ContextHelpButton:pressed {{ background: {c["btn_pressed_bg"]}; }}
        """

        custom = theme.get("custom_qss", "")
        if isinstance(custom, str) and custom.strip():
            qss += "\n\n/* --- Custom QSS override --- */\n" + custom + "\n"

        return qss

    def apply_to_app(self, app) -> QIcon | None:
        theme = self.load_theme(self.current_theme_name())
        colors = dict(theme.get("colors", {})) if isinstance(theme.get("colors"), dict) else {}

        base_font = _font_from_str(theme["fonts"].get("base", ""), QFont())
        app.setFont(base_font)

        app.setStyleSheet(self._build_stylesheet(theme))
        app.setProperty("gridoryn_theme_colors", colors)

        try:
            c = colors
            pal = QPalette(app.palette())
            pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(c.get("search_placeholder_fg", "#666666")))
            app.setPalette(pal)
        except Exception:
            pass

        icon = self.icon_for_theme(theme)
        if icon is not None:
            app.setWindowIcon(icon)

        return icon
