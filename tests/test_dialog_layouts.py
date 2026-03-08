from __future__ import annotations

from PySide6.QtCore import QSettings

from columns_ui import AddColumnDialog, RemoveColumnDialog
from settings_ui import SettingsDialog
from template_vars_ui import TemplateVariablesDialog
from ui_layout import EmptyStateStack, SectionPanel


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
