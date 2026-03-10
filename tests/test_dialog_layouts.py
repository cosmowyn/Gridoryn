from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QSettings

from columns_ui import AddColumnDialog, RemoveColumnDialog
from help_ui import HelpDialog, _build_help_html
from settings_ui import SettingsDialog
from template_vars_ui import TemplateVariablesDialog
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    button_minimum_size,
    polish_button_layouts,
)


def test_settings_dialog_uses_section_based_workspace_layout(qapp):
    dialog = SettingsDialog(QSettings())

    assert set(dialog._section_columns) == {"left", "right"}
    assert dialog._section_columns["left"].count() > 1
    assert dialog._section_columns["right"].count() > 1

    section_titles = {
        panel.title_label.text()
        for panel in dialog.findChildren(SectionPanel)
    }
    assert "Theme management" in section_titles
    assert "Fonts" in section_titles
    assert "Clock widget colors" in section_titles


def test_custom_column_dialogs_use_structured_sections(qapp):
    add_dialog = AddColumnDialog()
    assert add_dialog.findChildren(SectionPanel)

    remove_dialog = RemoveColumnDialog([])
    assert remove_dialog.findChildren(SectionPanel)
    assert remove_dialog.findChildren(EmptyStateStack)
    assert not remove_dialog.ok.isEnabled()


def test_template_variables_dialog_uses_local_scrollable_section(qapp):
    dialog = TemplateVariablesDialog(
        [f"value_{idx}" for idx in range(12)] + ["due_date"]
    )

    assert dialog.findChildren(SectionPanel)
    assert dialog.form_scroll.widgetResizable()
    assert dialog.form_stack.content_widget() is dialog.form_scroll
    assert dialog.apply_btn.isEnabled()


def test_polish_button_layouts_enforces_spacing_and_content_minimums(qapp):
    root = QWidget()
    outer = QVBoxLayout(root)
    row = QHBoxLayout()
    row.setSpacing(0)
    outer.addLayout(row)

    first = QPushButton("Open review workflow")
    second = QPushButton("Close")
    row.addWidget(first)
    row.addWidget(second)

    polish_button_layouts(root)

    assert row.spacing() >= 2
    assert first.minimumWidth() >= button_minimum_size(first).width()
    assert second.minimumWidth() >= button_minimum_size(second).width()


def test_help_dialog_buttons_get_sane_minimum_widths(qapp):
    dialog = HelpDialog()

    assert dialog.btn_find_next.minimumWidth() >= button_minimum_size(
        dialog.btn_find_next
    ).width()
    assert dialog.btn_find_prev.minimumWidth() >= button_minimum_size(
        dialog.btn_find_prev
    ).width()
    assert dialog.btn_home.minimumWidth() >= button_minimum_size(
        dialog.btn_home
    ).width()


def test_help_html_uses_runtime_app_font_not_apple_system_alias(qapp):
    html = _build_help_html()

    assert "-apple-system" not in html
    assert "font-family:" in html


def test_settings_dialog_border_width_controls_support_floats(qapp):
    dialog = SettingsDialog(QSettings())

    width_widget = dialog._border_widgets["headers"]["top"]["width"]
    assert isinstance(width_widget, QDoubleSpinBox)

    dialog._theme["borders"]["headers"]["top"]["width"] = 1.5
    dialog._load_theme_into_controls()
    assert width_widget.value() == 1.5

    width_widget.setValue(2.25)
    dialog._pull_controls_into_theme()
    assert dialog._theme["borders"]["headers"]["top"]["width"] == 2.25
