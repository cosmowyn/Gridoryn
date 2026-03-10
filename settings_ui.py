from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QColorDialog, QFontDialog, QFileDialog, QLineEdit,
    QFormLayout, QPlainTextEdit, QMessageBox,
    QInputDialog, QScrollArea, QWidget, QCheckBox, QSpinBox, QGridLayout, QSizePolicy
)

from theme import ThemeManager, default_theme_dict
from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
    configure_grid_layout,
    polish_button_layouts,
)


BORDER_STYLES = ["solid", "dash", "dot", "dashdot", "dashdotdot"]
COLOR_BUTTON_MIN_WIDTH = 220
COLOR_BUTTON_MIN_HEIGHT = 36
SETTINGS_EDITOR_MIN_WIDTH = 1020


def _set_color_btn(btn: QPushButton, color: str):
    btn.setMinimumWidth(COLOR_BUTTON_MIN_WIDTH)
    btn.setMinimumHeight(max(COLOR_BUTTON_MIN_HEIGHT, btn.fontMetrics().height() + 16))
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setText(color)
    btn.setStyleSheet(
        f"background: {color};"
        " border: 1px solid rgba(0,0,0,0.20);"
        " padding: 8px 14px;"
        " text-align: left;"
    )


def _font_label(font: QFont) -> str:
    return f"{font.family()} {max(font.pointSize(), 10)}pt"


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings & Themes")
        self.setMinimumSize(860, 800)

        self.tm = ThemeManager(settings)

        self._theme_name: str = self.tm.current_theme_name()
        self._theme: dict = self.tm.load_theme(self._theme_name)

        self._border_widgets: dict[str, dict[str, dict[str, object]]] = {}
        self._section_columns: dict[str, QVBoxLayout] = {}

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.tm.list_themes())
        self.theme_combo.setCurrentText(self._theme_name)
        self.theme_combo.currentTextChanged.connect(self._on_theme_selected)

        self.btn_new = QPushButton("New")
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save as…")
        self.btn_delete = QPushButton("Delete")

        self.btn_new.clicked.connect(self._new_theme)
        self.btn_save.clicked.connect(self._save_theme)
        self.btn_save_as.clicked.connect(self._save_as_theme)
        self.btn_delete.clicked.connect(self._delete_theme)

        theme_group = SectionPanel(
            "Theme management",
            "Select, create, save, and remove local appearance presets.",
        )
        theme_form = QFormLayout()
        configure_form_layout(theme_form, label_width=140)
        add_form_row(theme_form, "Active theme", self.theme_combo)
        theme_group.body_layout.addLayout(theme_form)
        theme_actions = QHBoxLayout()
        add_left_aligned_buttons(
            theme_actions,
            self.btn_new,
            self.btn_save,
            self.btn_save_as,
            self.btn_delete,
        )
        theme_group.body_layout.addLayout(theme_actions)
        root.addWidget(theme_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(scroll, 1)

        editor = QWidget()
        editor.setMinimumWidth(SETTINGS_EDITOR_MIN_WIDTH)
        editor_layout = QHBoxLayout(editor)
        configure_box_layout(editor_layout, margins=(0, 0, 0, 0), spacing=10)

        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        configure_box_layout(left_column, spacing=10)
        configure_box_layout(right_column, spacing=10)
        editor_layout.addLayout(left_column, 1)
        editor_layout.addLayout(right_column, 1)

        self._section_columns = {
            "left": left_column,
            "right": right_column,
        }
        scroll.setWidget(editor)

        self._build_application_group()
        self._build_fonts_group()
        self._build_search_group()
        self._build_row_action_buttons_group()
        self._build_window_group()
        self._build_menus_toolbar_group()
        self._build_header_group()
        self._build_tree_group()
        self._build_buttons_group()
        self._build_inputs_group()
        self._build_gantt_group()
        self._build_clock_group()
        self._build_selection_group()
        self._build_border_groups()
        self._build_advanced_group()

        left_column.addStretch(1)
        right_column.addStretch(1)

        bottom = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        add_left_aligned_buttons(bottom, ok, cancel)
        root.addLayout(bottom)

        polish_button_layouts(self)
        self._load_theme_into_controls()

    def _add_section_widget(
        self,
        widget: QWidget,
        column: str = "left",
    ):
        target = self._section_columns.get(column, self._section_columns["left"])
        target.addWidget(widget)

    def _mk_group(
        self,
        title: str,
        *,
        column: str = "left",
        subtitle: str = "",
    ) -> QWidget:
        panel = SectionPanel(title, subtitle)
        panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        g = QWidget()
        form = QFormLayout()
        configure_form_layout(form, label_width=190)
        form.setVerticalSpacing(12)
        g.setLayout(form)
        panel.body_layout.addWidget(g)
        self._add_section_widget(panel, column)
        return g

    def _wrap_row(self, lbl: QLabel, btn: QPushButton) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        configure_box_layout(h)
        h.addWidget(lbl, 1)
        h.addWidget(btn)
        return w

    def _mk_font_row(self, handler):
        lbl = QLabel("")
        btn = QPushButton("Choose…")
        btn.clicked.connect(handler)
        return lbl, btn

    def _build_application_group(self):
        g = self._mk_group(
            "Application",
            column="left",
            subtitle="Core application identity and icon settings.",
        )

        row = QHBoxLayout()
        configure_box_layout(row)
        self.icon_path = QLineEdit()
        self.btn_browse_icon = QPushButton("Browse…")
        self.btn_browse_icon.clicked.connect(self._browse_icon)
        row.addWidget(self.icon_path, 1)
        row.addWidget(self.btn_browse_icon)

        w = QWidget()
        w.setLayout(row)
        g.layout().addRow("App icon", w)

    def _build_fonts_group(self):
        g = self._mk_group(
            "Fonts",
            column="left",
            subtitle="Separate font choices for major parts of the interface.",
        )

        self.font_base_lbl, self.font_base_btn = self._mk_font_row(self._choose_font_base)
        g.layout().addRow("Base", self._wrap_row(self.font_base_lbl, self.font_base_btn))

        self.font_header_lbl, self.font_header_btn = self._mk_font_row(self._choose_font_header)
        g.layout().addRow("Header", self._wrap_row(self.font_header_lbl, self.font_header_btn))

        self.font_tree_lbl, self.font_tree_btn = self._mk_font_row(self._choose_font_tree)
        g.layout().addRow("Tree/Table", self._wrap_row(self.font_tree_lbl, self.font_tree_btn))

        self.font_button_lbl, self.font_button_btn = self._mk_font_row(self._choose_font_button)
        g.layout().addRow("Buttons", self._wrap_row(self.font_button_lbl, self.font_button_btn))

        self.font_input_lbl, self.font_input_btn = self._mk_font_row(self._choose_font_input)
        g.layout().addRow("Inputs", self._wrap_row(self.font_input_lbl, self.font_input_btn))

        self.font_menu_lbl, self.font_menu_btn = self._mk_font_row(self._choose_font_menu)
        g.layout().addRow("Menus", self._wrap_row(self.font_menu_lbl, self.font_menu_btn))

        self.font_search_lbl, self.font_search_btn = self._mk_font_row(self._choose_font_search)
        g.layout().addRow("Search bar", self._wrap_row(self.font_search_lbl, self.font_search_btn))

    def _build_search_group(self):
        g = self._mk_group(
            "Search bar styling",
            column="left",
            subtitle="Colors for the main search field and its clear button.",
        )

        self.search_bg_btn = QPushButton()
        self.search_fg_btn = QPushButton()
        self.search_border_btn = QPushButton()
        self.search_focus_border_btn = QPushButton()
        self.search_placeholder_fg_btn = QPushButton()

        self.search_clear_bg_btn = QPushButton()
        self.search_clear_fg_btn = QPushButton()
        self.search_clear_border_btn = QPushButton()
        self.search_clear_hover_bg_btn = QPushButton()
        self.search_clear_pressed_bg_btn = QPushButton()

        self.search_bg_btn.clicked.connect(lambda: self._color_pick("search_bg", self.search_bg_btn))
        self.search_fg_btn.clicked.connect(lambda: self._color_pick("search_fg", self.search_fg_btn))
        self.search_border_btn.clicked.connect(lambda: self._color_pick("search_border", self.search_border_btn))
        self.search_focus_border_btn.clicked.connect(lambda: self._color_pick("search_focus_border", self.search_focus_border_btn))
        self.search_placeholder_fg_btn.clicked.connect(lambda: self._color_pick("search_placeholder_fg", self.search_placeholder_fg_btn))

        self.search_clear_bg_btn.clicked.connect(lambda: self._color_pick("search_clear_bg", self.search_clear_bg_btn))
        self.search_clear_fg_btn.clicked.connect(lambda: self._color_pick("search_clear_fg", self.search_clear_fg_btn))
        self.search_clear_border_btn.clicked.connect(lambda: self._color_pick("search_clear_border", self.search_clear_border_btn))
        self.search_clear_hover_bg_btn.clicked.connect(lambda: self._color_pick("search_clear_hover_bg", self.search_clear_hover_bg_btn))
        self.search_clear_pressed_bg_btn.clicked.connect(lambda: self._color_pick("search_clear_pressed_bg", self.search_clear_pressed_bg_btn))

        g.layout().addRow("Bar background", self.search_bg_btn)
        g.layout().addRow("Bar text", self.search_fg_btn)
        g.layout().addRow("Bar border", self.search_border_btn)
        g.layout().addRow("Bar focus border", self.search_focus_border_btn)
        g.layout().addRow("Placeholder text", self.search_placeholder_fg_btn)

        g.layout().addRow("Clear button background", self.search_clear_bg_btn)
        g.layout().addRow("Clear button text", self.search_clear_fg_btn)
        g.layout().addRow("Clear button border", self.search_clear_border_btn)
        g.layout().addRow("Clear hover background", self.search_clear_hover_bg_btn)
        g.layout().addRow("Clear pressed background", self.search_clear_pressed_bg_btn)

    def _build_row_action_buttons_group(self):
        g = self._mk_group(
            "Row action buttons (+ / -)",
            column="right",
            subtitle="Theme the floating row add and remove controls.",
        )

        self.row_add_bg_btn = QPushButton()
        self.row_add_fg_btn = QPushButton()
        self.row_add_border_btn = QPushButton()
        self.row_add_hover_bg_btn = QPushButton()
        self.row_add_pressed_bg_btn = QPushButton()

        self.row_del_bg_btn = QPushButton()
        self.row_del_fg_btn = QPushButton()
        self.row_del_border_btn = QPushButton()
        self.row_del_hover_bg_btn = QPushButton()
        self.row_del_pressed_bg_btn = QPushButton()

        self.row_add_bg_btn.clicked.connect(lambda: self._color_pick("row_add_bg", self.row_add_bg_btn))
        self.row_add_fg_btn.clicked.connect(lambda: self._color_pick("row_add_fg", self.row_add_fg_btn))
        self.row_add_border_btn.clicked.connect(lambda: self._color_pick("row_add_border", self.row_add_border_btn))
        self.row_add_hover_bg_btn.clicked.connect(lambda: self._color_pick("row_add_hover_bg", self.row_add_hover_bg_btn))
        self.row_add_pressed_bg_btn.clicked.connect(lambda: self._color_pick("row_add_pressed_bg", self.row_add_pressed_bg_btn))

        self.row_del_bg_btn.clicked.connect(lambda: self._color_pick("row_del_bg", self.row_del_bg_btn))
        self.row_del_fg_btn.clicked.connect(lambda: self._color_pick("row_del_fg", self.row_del_fg_btn))
        self.row_del_border_btn.clicked.connect(lambda: self._color_pick("row_del_border", self.row_del_border_btn))
        self.row_del_hover_bg_btn.clicked.connect(lambda: self._color_pick("row_del_hover_bg", self.row_del_hover_bg_btn))
        self.row_del_pressed_bg_btn.clicked.connect(lambda: self._color_pick("row_del_pressed_bg", self.row_del_pressed_bg_btn))

        g.layout().addRow("Add (+) background", self.row_add_bg_btn)
        g.layout().addRow("Add (+) text", self.row_add_fg_btn)
        g.layout().addRow("Add (+) border", self.row_add_border_btn)
        g.layout().addRow("Add (+) hover bg", self.row_add_hover_bg_btn)
        g.layout().addRow("Add (+) pressed bg", self.row_add_pressed_bg_btn)

        g.layout().addRow("Delete (–) background", self.row_del_bg_btn)
        g.layout().addRow("Delete (–) text", self.row_del_fg_btn)
        g.layout().addRow("Delete (–) border", self.row_del_border_btn)
        g.layout().addRow("Delete (–) hover bg", self.row_del_hover_bg_btn)
        g.layout().addRow("Delete (–) pressed bg", self.row_del_pressed_bg_btn)

    def _build_window_group(self):
        g = self._mk_group(
            "Window & general colors",
            column="left",
            subtitle="Base window background and foreground colors.",
        )
        self.window_bg_btn = QPushButton()
        self.window_fg_btn = QPushButton()
        self.window_bg_btn.clicked.connect(lambda: self._color_pick("window_bg", self.window_bg_btn))
        self.window_fg_btn.clicked.connect(lambda: self._color_pick("window_fg", self.window_fg_btn))
        g.layout().addRow("Window background", self.window_bg_btn)
        g.layout().addRow("Text color", self.window_fg_btn)

    def _build_menus_toolbar_group(self):
        g = self._mk_group(
            "Menus & toolbar colors",
            column="right",
            subtitle="Menu bar, menu, and toolbar appearance.",
        )
        self.menubar_bg_btn = QPushButton()
        self.menu_bg_btn = QPushButton()
        self.menu_fg_btn = QPushButton()
        self.menu_border_btn = QPushButton()
        self.toolbar_bg_btn = QPushButton()
        self.toolbar_border_btn = QPushButton()

        self.menubar_bg_btn.clicked.connect(lambda: self._color_pick("menubar_bg", self.menubar_bg_btn))
        self.menu_bg_btn.clicked.connect(lambda: self._color_pick("menu_bg", self.menu_bg_btn))
        self.menu_fg_btn.clicked.connect(lambda: self._color_pick("menu_fg", self.menu_fg_btn))
        self.menu_border_btn.clicked.connect(lambda: self._color_pick("menu_border", self.menu_border_btn))
        self.toolbar_bg_btn.clicked.connect(lambda: self._color_pick("toolbar_bg", self.toolbar_bg_btn))
        self.toolbar_border_btn.clicked.connect(lambda: self._color_pick("toolbar_border", self.toolbar_border_btn))

        g.layout().addRow("Menu bar background", self.menubar_bg_btn)
        g.layout().addRow("Menu background", self.menu_bg_btn)
        g.layout().addRow("Menu text", self.menu_fg_btn)
        g.layout().addRow("Menu border", self.menu_border_btn)
        g.layout().addRow("Toolbar background", self.toolbar_bg_btn)
        g.layout().addRow("Toolbar border", self.toolbar_border_btn)

    def _build_header_group(self):
        g = self._mk_group(
            "Header colors",
            column="left",
            subtitle="Table and section header colors.",
        )
        self.header_bg_btn = QPushButton()
        self.header_fg_btn = QPushButton()
        self.header_border_btn = QPushButton()
        self.header_bg_btn.clicked.connect(lambda: self._color_pick("header_bg", self.header_bg_btn))
        self.header_fg_btn.clicked.connect(lambda: self._color_pick("header_fg", self.header_fg_btn))
        self.header_border_btn.clicked.connect(lambda: self._color_pick("header_border", self.header_border_btn))
        g.layout().addRow("Header background", self.header_bg_btn)
        g.layout().addRow("Header text", self.header_fg_btn)
        g.layout().addRow("Header default border color", self.header_border_btn)

    def _build_tree_group(self):
        g = self._mk_group(
            "Tree/Table colors",
            column="right",
            subtitle="Task tree background, text, and grid colors.",
        )
        self.tree_bg_btn = QPushButton()
        self.tree_alt_bg_btn = QPushButton()
        self.tree_fg_btn = QPushButton()
        self.grid_btn = QPushButton()

        self.tree_bg_btn.clicked.connect(lambda: self._color_pick("tree_bg", self.tree_bg_btn))
        self.tree_alt_bg_btn.clicked.connect(lambda: self._color_pick("tree_alt_bg", self.tree_alt_bg_btn))
        self.tree_fg_btn.clicked.connect(lambda: self._color_pick("tree_fg", self.tree_fg_btn))
        self.grid_btn.clicked.connect(lambda: self._color_pick("grid", self.grid_btn))

        g.layout().addRow("Background", self.tree_bg_btn)
        g.layout().addRow("Alternate row background", self.tree_alt_bg_btn)
        g.layout().addRow("Text", self.tree_fg_btn)
        g.layout().addRow("Gridlines", self.grid_btn)

    def _build_buttons_group(self):
        g = self._mk_group(
            "Buttons colors",
            column="right",
            subtitle="Primary button states across the application.",
        )
        self.btn_bg_btn = QPushButton()
        self.btn_fg_btn = QPushButton()
        self.btn_border_btn = QPushButton()
        self.btn_hover_bg_btn = QPushButton()
        self.btn_pressed_bg_btn = QPushButton()
        self.btn_disabled_bg_btn = QPushButton()
        self.btn_disabled_fg_btn = QPushButton()

        self.btn_bg_btn.clicked.connect(lambda: self._color_pick("btn_bg", self.btn_bg_btn))
        self.btn_fg_btn.clicked.connect(lambda: self._color_pick("btn_fg", self.btn_fg_btn))
        self.btn_border_btn.clicked.connect(lambda: self._color_pick("btn_border", self.btn_border_btn))
        self.btn_hover_bg_btn.clicked.connect(lambda: self._color_pick("btn_hover_bg", self.btn_hover_bg_btn))
        self.btn_pressed_bg_btn.clicked.connect(lambda: self._color_pick("btn_pressed_bg", self.btn_pressed_bg_btn))
        self.btn_disabled_bg_btn.clicked.connect(lambda: self._color_pick("btn_disabled_bg", self.btn_disabled_bg_btn))
        self.btn_disabled_fg_btn.clicked.connect(lambda: self._color_pick("btn_disabled_fg", self.btn_disabled_fg_btn))

        g.layout().addRow("Background", self.btn_bg_btn)
        g.layout().addRow("Text", self.btn_fg_btn)
        g.layout().addRow("Border", self.btn_border_btn)
        g.layout().addRow("Hover background", self.btn_hover_bg_btn)
        g.layout().addRow("Pressed background", self.btn_pressed_bg_btn)
        g.layout().addRow("Disabled background", self.btn_disabled_bg_btn)
        g.layout().addRow("Disabled text", self.btn_disabled_fg_btn)

    def _build_inputs_group(self):
        g = self._mk_group(
            "Inputs (editors) colors",
            column="left",
            subtitle="Editor fields and focused input styling.",
        )
        self.input_bg_btn = QPushButton()
        self.input_fg_btn = QPushButton()
        self.input_border_btn = QPushButton()
        self.input_focus_border_btn = QPushButton()

        self.input_bg_btn.clicked.connect(lambda: self._color_pick("input_bg", self.input_bg_btn))
        self.input_fg_btn.clicked.connect(lambda: self._color_pick("input_fg", self.input_fg_btn))
        self.input_border_btn.clicked.connect(lambda: self._color_pick("input_border", self.input_border_btn))
        self.input_focus_border_btn.clicked.connect(lambda: self._color_pick("input_focus_border", self.input_focus_border_btn))

        g.layout().addRow("Background", self.input_bg_btn)
        g.layout().addRow("Text", self.input_fg_btn)
        g.layout().addRow("Border", self.input_border_btn)
        g.layout().addRow("Focus border", self.input_focus_border_btn)

    def _build_clock_group(self):
        g = self._mk_group(
            "Clock widget colors",
            column="right",
            subtitle="Colors for the radial time picker widget.",
        )

        self.clock_face_bg_btn = QPushButton()
        self.clock_face_border_btn = QPushButton()
        self.clock_text_btn = QPushButton()
        self.clock_tick_btn = QPushButton()
        self.clock_hand_btn = QPushButton()
        self.clock_accent_btn = QPushButton()
        self.clock_accent_text_btn = QPushButton()
        self.clock_center_dot_btn = QPushButton()

        self.clock_face_bg_btn.clicked.connect(lambda: self._color_pick("clock_face_bg", self.clock_face_bg_btn))
        self.clock_face_border_btn.clicked.connect(lambda: self._color_pick("clock_face_border", self.clock_face_border_btn))
        self.clock_text_btn.clicked.connect(lambda: self._color_pick("clock_text", self.clock_text_btn))
        self.clock_tick_btn.clicked.connect(lambda: self._color_pick("clock_tick", self.clock_tick_btn))
        self.clock_hand_btn.clicked.connect(lambda: self._color_pick("clock_hand", self.clock_hand_btn))
        self.clock_accent_btn.clicked.connect(lambda: self._color_pick("clock_accent", self.clock_accent_btn))
        self.clock_accent_text_btn.clicked.connect(lambda: self._color_pick("clock_accent_text", self.clock_accent_text_btn))
        self.clock_center_dot_btn.clicked.connect(lambda: self._color_pick("clock_center_dot", self.clock_center_dot_btn))

        g.layout().addRow("Clock face background", self.clock_face_bg_btn)
        g.layout().addRow("Clock face border", self.clock_face_border_btn)
        g.layout().addRow("Clock numbers", self.clock_text_btn)
        g.layout().addRow("Minute tick marks", self.clock_tick_btn)
        g.layout().addRow("Clock hand", self.clock_hand_btn)
        g.layout().addRow("Selected value fill", self.clock_accent_btn)
        g.layout().addRow("Selected value text", self.clock_accent_text_btn)
        g.layout().addRow("Center dot", self.clock_center_dot_btn)

    def _build_gantt_group(self):
        g = self._mk_group(
            "Gantt bar colors",
            column="right",
            subtitle="Colors for ordinary task bars and parent/summary bars in the timeline.",
        )

        self.gantt_task_bg_btn = QPushButton()
        self.gantt_task_text_btn = QPushButton()
        self.gantt_summary_bg_btn = QPushButton()
        self.gantt_summary_text_btn = QPushButton()

        self.gantt_task_bg_btn.clicked.connect(lambda: self._color_pick("gantt_task_bg", self.gantt_task_bg_btn))
        self.gantt_task_text_btn.clicked.connect(lambda: self._color_pick("gantt_task_text", self.gantt_task_text_btn))
        self.gantt_summary_bg_btn.clicked.connect(lambda: self._color_pick("gantt_summary_bg", self.gantt_summary_bg_btn))
        self.gantt_summary_text_btn.clicked.connect(lambda: self._color_pick("gantt_summary_text", self.gantt_summary_text_btn))

        g.layout().addRow("Task bar background", self.gantt_task_bg_btn)
        g.layout().addRow("Task bar text", self.gantt_task_text_btn)
        g.layout().addRow("Summary bar background", self.gantt_summary_bg_btn)
        g.layout().addRow("Summary bar text", self.gantt_summary_text_btn)

    def _build_selection_group(self):
        g = self._mk_group(
            "Selection colors",
            column="left",
            subtitle="Highlight colors used for selected rows and text.",
        )
        self.sel_bg_btn = QPushButton()
        self.sel_fg_btn = QPushButton()
        self.sel_bg_btn.clicked.connect(lambda: self._color_pick("sel_bg", self.sel_bg_btn))
        self.sel_fg_btn.clicked.connect(lambda: self._color_pick("sel_fg", self.sel_fg_btn))
        g.layout().addRow("Selection background", self.sel_bg_btn)
        g.layout().addRow("Selection text", self.sel_fg_btn)

    def _build_border_groups(self):
        self._build_border_group("Header borders", "headers")
        self._build_border_group("Cell borders", "cells")
        self._build_border_group("Sibling borders", "siblings")

    def _build_border_group(self, title: str, section: str):
        panel = SectionPanel(
            title,
            "Configure each side independently for precise divider styling.",
        )
        group = QWidget()
        layout = QGridLayout(group)
        configure_grid_layout(layout)
        layout.addWidget(QLabel("Side"), 0, 0)
        layout.addWidget(QLabel("Enabled"), 0, 1)
        layout.addWidget(QLabel("Width"), 0, 2)
        layout.addWidget(QLabel("Style"), 0, 3)
        layout.addWidget(QLabel("Color"), 0, 4)

        self._border_widgets[section] = {}

        for row_idx, side in enumerate(("top", "right", "bottom", "left"), start=1):
            enabled = QCheckBox()
            width = QSpinBox()
            width.setRange(0, 20)
            width.setSuffix(" px")
            width.setMinimumWidth(90)

            color_btn = QPushButton()
            style_cb = QComboBox()
            style_cb.addItems(BORDER_STYLES)
            style_cb.setMinimumWidth(130)
            _set_color_btn(color_btn, "#000000")

            color_btn.clicked.connect(lambda _=False, s=section, sd=side, b=color_btn: self._pick_border_color(s, sd, b))

            layout.addWidget(QLabel(side.capitalize()), row_idx, 0)
            layout.addWidget(enabled, row_idx, 1)
            layout.addWidget(width, row_idx, 2)
            layout.addWidget(style_cb, row_idx, 3)
            layout.addWidget(color_btn, row_idx, 4)

            self._border_widgets[section][side] = {
                "enabled": enabled,
                "width": width,
                "style": style_cb,
                "color_btn": color_btn,
            }

        layout.setColumnMinimumWidth(2, 90)
        layout.setColumnMinimumWidth(3, 130)
        layout.setColumnMinimumWidth(4, COLOR_BUTTON_MIN_WIDTH)
        layout.setColumnStretch(4, 1)
        panel.body_layout.addWidget(group)
        self._add_section_widget(panel, "right")

    def _build_advanced_group(self):
        g = self._mk_group(
            "Advanced",
            column="left",
            subtitle="Optional custom Qt StyleSheet overrides.",
        )
        self.custom_qss = QPlainTextEdit()
        self.custom_qss.setMinimumHeight(180)
        self.custom_qss.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.custom_qss.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.custom_qss.setPlaceholderText(
            "Optional: add custom Qt StyleSheet (QSS) here.\n"
            "This is appended after the generated theme QSS, so it can override anything.\n"
            "See Help > QSS Styling for stable object names and selector examples.\n"
        )
        add_form_row(g.layout(), "Custom QSS override", self.custom_qss)

    def _on_theme_selected(self, name: str):
        if not name:
            return
        self._theme_name = name
        self._theme = self.tm.load_theme(name)
        self._load_theme_into_controls()

    def _new_theme(self):
        name, ok = QInputDialog.getText(self, "New theme", "Theme name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return

        self.tm.duplicate_theme(self._theme_name, name)
        self.theme_combo.clear()
        self.theme_combo.addItems(self.tm.list_themes())
        self.theme_combo.setCurrentText(name)

    def _save_theme(self):
        self._pull_controls_into_theme()
        self.tm.save_theme(self._theme_name, self._theme)
        self.tm.set_current_theme(self._theme_name)

    def _save_as_theme(self):
        name, ok = QInputDialog.getText(self, "Save theme as", "New theme name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return

        self._pull_controls_into_theme()
        self.tm.save_theme(name, self._theme)
        self.tm.set_current_theme(name)

        self.theme_combo.clear()
        self.theme_combo.addItems(self.tm.list_themes())
        self.theme_combo.setCurrentText(name)

    def _delete_theme(self):
        name = self._theme_name
        if len(self.tm.list_themes()) <= 1:
            QMessageBox.information(self, "Not possible", "At least one theme must remain.")
            return

        res = QMessageBox.question(self, "Delete theme", f"Delete theme '{name}'?")
        if res != QMessageBox.StandardButton.Yes:
            return

        self.tm.delete_theme(name)
        self.theme_combo.clear()
        self.theme_combo.addItems(self.tm.list_themes())
        self.theme_combo.setCurrentText(self.tm.current_theme_name())

    def _ok(self):
        self._save_theme()
        self.accept()

    def _load_theme_into_controls(self):
        d = default_theme_dict()
        t = d
        t.update(self._theme)
        t["fonts"].update(self._theme.get("fonts", {}))
        t["colors"].update(self._theme.get("colors", {}))

        tb = self._theme.get("borders", {})
        for section in ("headers", "cells", "siblings"):
            dsec = d["borders"].get(section, {})
            tsec = tb.get(section, {}) if isinstance(tb.get(section, {}), dict) else {}
            merged = {}
            for side in ("top", "right", "bottom", "left"):
                side_default = dict(dsec.get(side, {}))
                side_theme = tsec.get(side, {}) if isinstance(tsec.get(side, {}), dict) else {}
                side_default.update(side_theme)
                merged[side] = side_default
            t["borders"][section] = merged

        self._theme = t

        self.icon_path.setText(self._theme.get("app_icon_path", ""))
        self._update_font_labels()

        c = self._theme["colors"]

        _set_color_btn(self.search_bg_btn, c["search_bg"])
        _set_color_btn(self.search_fg_btn, c["search_fg"])
        _set_color_btn(self.search_border_btn, c["search_border"])
        _set_color_btn(self.search_focus_border_btn, c["search_focus_border"])
        _set_color_btn(self.search_placeholder_fg_btn, c["search_placeholder_fg"])

        _set_color_btn(self.search_clear_bg_btn, c["search_clear_bg"])
        _set_color_btn(self.search_clear_fg_btn, c["search_clear_fg"])
        _set_color_btn(self.search_clear_border_btn, c["search_clear_border"])
        _set_color_btn(self.search_clear_hover_bg_btn, c["search_clear_hover_bg"])
        _set_color_btn(self.search_clear_pressed_bg_btn, c["search_clear_pressed_bg"])

        _set_color_btn(self.row_add_bg_btn, c["row_add_bg"])
        _set_color_btn(self.row_add_fg_btn, c["row_add_fg"])
        _set_color_btn(self.row_add_border_btn, c["row_add_border"])
        _set_color_btn(self.row_add_hover_bg_btn, c["row_add_hover_bg"])
        _set_color_btn(self.row_add_pressed_bg_btn, c["row_add_pressed_bg"])

        _set_color_btn(self.row_del_bg_btn, c["row_del_bg"])
        _set_color_btn(self.row_del_fg_btn, c["row_del_fg"])
        _set_color_btn(self.row_del_border_btn, c["row_del_border"])
        _set_color_btn(self.row_del_hover_bg_btn, c["row_del_hover_bg"])
        _set_color_btn(self.row_del_pressed_bg_btn, c["row_del_pressed_bg"])

        _set_color_btn(self.window_bg_btn, c["window_bg"])
        _set_color_btn(self.window_fg_btn, c["window_fg"])

        _set_color_btn(self.menubar_bg_btn, c["menubar_bg"])
        _set_color_btn(self.menu_bg_btn, c["menu_bg"])
        _set_color_btn(self.menu_fg_btn, c["menu_fg"])
        _set_color_btn(self.menu_border_btn, c["menu_border"])
        _set_color_btn(self.toolbar_bg_btn, c["toolbar_bg"])
        _set_color_btn(self.toolbar_border_btn, c["toolbar_border"])

        _set_color_btn(self.header_bg_btn, c["header_bg"])
        _set_color_btn(self.header_fg_btn, c["header_fg"])
        _set_color_btn(self.header_border_btn, c["header_border"])

        _set_color_btn(self.tree_bg_btn, c["tree_bg"])
        _set_color_btn(self.tree_alt_bg_btn, c["tree_alt_bg"])
        _set_color_btn(self.tree_fg_btn, c["tree_fg"])
        _set_color_btn(self.grid_btn, c["grid"])

        _set_color_btn(self.btn_bg_btn, c["btn_bg"])
        _set_color_btn(self.btn_fg_btn, c["btn_fg"])
        _set_color_btn(self.btn_border_btn, c["btn_border"])
        _set_color_btn(self.btn_hover_bg_btn, c["btn_hover_bg"])
        _set_color_btn(self.btn_pressed_bg_btn, c["btn_pressed_bg"])
        _set_color_btn(self.btn_disabled_bg_btn, c["btn_disabled_bg"])
        _set_color_btn(self.btn_disabled_fg_btn, c["btn_disabled_fg"])

        _set_color_btn(self.input_bg_btn, c["input_bg"])
        _set_color_btn(self.input_fg_btn, c["input_fg"])
        _set_color_btn(self.input_border_btn, c["input_border"])
        _set_color_btn(self.input_focus_border_btn, c["input_focus_border"])

        _set_color_btn(self.gantt_task_bg_btn, c["gantt_task_bg"])
        _set_color_btn(self.gantt_task_text_btn, c["gantt_task_text"])
        _set_color_btn(self.gantt_summary_bg_btn, c["gantt_summary_bg"])
        _set_color_btn(self.gantt_summary_text_btn, c["gantt_summary_text"])

        _set_color_btn(self.clock_face_bg_btn, c["clock_face_bg"])
        _set_color_btn(self.clock_face_border_btn, c["clock_face_border"])
        _set_color_btn(self.clock_text_btn, c["clock_text"])
        _set_color_btn(self.clock_tick_btn, c["clock_tick"])
        _set_color_btn(self.clock_hand_btn, c["clock_hand"])
        _set_color_btn(self.clock_accent_btn, c["clock_accent"])
        _set_color_btn(self.clock_accent_text_btn, c["clock_accent_text"])
        _set_color_btn(self.clock_center_dot_btn, c["clock_center_dot"])

        _set_color_btn(self.sel_bg_btn, c["sel_bg"])
        _set_color_btn(self.sel_fg_btn, c["sel_fg"])

        for section in ("headers", "cells", "siblings"):
            for side in ("top", "right", "bottom", "left"):
                cfg = self._theme["borders"][section][side]
                w = self._border_widgets[section][side]
                w["enabled"].setChecked(bool(cfg.get("enabled", False)))
                w["width"].setValue(int(cfg.get("width", 0)))
                style_cb = w["style"]
                style = str(cfg.get("style", "solid"))
                idx = style_cb.findText(style)
                style_cb.setCurrentIndex(idx if idx >= 0 else 0)
                _set_color_btn(w["color_btn"], str(cfg.get("color", "#000000")))

        self.custom_qss.setPlainText(self._theme.get("custom_qss", ""))

    def _pull_controls_into_theme(self):
        self._theme["app_icon_path"] = self.icon_path.text().strip()
        self._theme["custom_qss"] = self.custom_qss.toPlainText()

        for section in ("headers", "cells", "siblings"):
            if "borders" not in self._theme:
                self._theme["borders"] = {}
            if section not in self._theme["borders"]:
                self._theme["borders"][section] = {}

            for side in ("top", "right", "bottom", "left"):
                w = self._border_widgets[section][side]
                self._theme["borders"][section][side] = {
                    "enabled": bool(w["enabled"].isChecked()),
                    "width": int(w["width"].value()),
                    "style": str(w["style"].currentText()),
                    "color": str(w["color_btn"].text()),
                }

    def _color_pick(self, key: str, btn: QPushButton):
        chosen = QColorDialog.getColor(parent=self)
        if chosen.isValid():
            self._theme["colors"][key] = chosen.name()
            _set_color_btn(btn, chosen.name())

    def _pick_border_color(self, section: str, side: str, btn: QPushButton):
        chosen = QColorDialog.getColor(parent=self)
        if chosen.isValid():
            self._theme.setdefault("borders", {}).setdefault(section, {}).setdefault(side, {})
            self._theme["borders"][section][side]["color"] = chosen.name()
            _set_color_btn(btn, chosen.name())

    def _browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose application icon",
            "",
            "Icons (*.ico *.png *.jpg *.jpeg *.bmp *.icns);;All files (*.*)",
        )
        if path:
            self.icon_path.setText(path)

    def _update_font_labels(self):
        from theme import _font_from_str

        base = _font_from_str(self._theme["fonts"].get("base", ""), QFont("Segoe UI", 10))
        header = _font_from_str(self._theme["fonts"].get("header", ""), base)
        tree = _font_from_str(self._theme["fonts"].get("tree", ""), base)
        button = _font_from_str(self._theme["fonts"].get("button", ""), base)
        input_f = _font_from_str(self._theme["fonts"].get("input", ""), base)
        menu = _font_from_str(self._theme["fonts"].get("menu", ""), base)
        search = _font_from_str(self._theme["fonts"].get("search", ""), input_f)

        self.font_base_lbl.setText(_font_label(base))
        self.font_header_lbl.setText(_font_label(header))
        self.font_tree_lbl.setText(_font_label(tree))
        self.font_button_lbl.setText(_font_label(button))
        self.font_input_lbl.setText(_font_label(input_f))
        self.font_menu_lbl.setText(_font_label(menu))
        self.font_search_lbl.setText(_font_label(search))

    def _choose_font_base(self):
        self._choose_font("base", QFont("Segoe UI", 10))

    def _choose_font_header(self):
        self._choose_font("header", QFont("Segoe UI", 10, QFont.Weight.DemiBold))

    def _choose_font_tree(self):
        self._choose_font("tree", QFont("Segoe UI", 10))

    def _choose_font_button(self):
        self._choose_font("button", QFont("Segoe UI", 10, QFont.Weight.Medium))

    def _choose_font_input(self):
        self._choose_font("input", QFont("Segoe UI", 10))

    def _choose_font_menu(self):
        self._choose_font("menu", QFont("Segoe UI", 10))

    def _choose_font_search(self):
        self._choose_font("search", QFont("Segoe UI", 10, QFont.Weight.Medium))

    def _choose_font(self, slot: str, fallback: QFont):
        from theme import _font_from_str, _font_to_str

        current = _font_from_str(self._theme["fonts"].get(slot, ""), fallback)
        ok, font = QFontDialog.getFont(current, self, f"Choose font ({slot})")
        if ok:
            self._theme["fonts"][slot] = _font_to_str(font)
            self._update_font_labels()
