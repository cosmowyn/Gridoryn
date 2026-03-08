from __future__ import annotations

from PySide6.QtWidgets import QWidget

from archive_ui import ArchiveBrowserDialog
from context_help import create_context_help_button, help_anchor_for_surface
from project_cockpit_ui import ProjectCockpitPanel
from relationships_ui import RelationshipsPanel
from ui_layout import SectionPanel


class _HelpHost(QWidget):
    def __init__(self):
        super().__init__()
        self.opened: list[str] = []

    def _open_help_anchor(self, anchor: str):
        self.opened.append(str(anchor))


def test_help_anchor_for_surface_returns_expected_topics():
    assert help_anchor_for_surface("relationships_panel") == "relationships"
    assert help_anchor_for_surface("project_cockpit") == "projects"
    assert help_anchor_for_surface("archive_browser") == "archive"
    assert help_anchor_for_surface("unknown_surface") is None


def test_context_help_button_uses_parent_help_opener(qapp):
    host = _HelpHost()
    button = create_context_help_button("relationships_panel", host)
    assert button is not None
    assert button.property("context_help_anchor") == "relationships"

    button.click()

    assert host.opened == ["relationships"]


def test_section_panel_hides_subtitle_and_uses_tooltip(qapp):
    panel = SectionPanel("Example", "Hidden helper copy")

    assert panel.subtitle_label.isHidden()
    assert panel.toolTip() == "Hidden helper copy"
    assert panel.title_label.toolTip() == "Hidden helper copy"


def test_panel_and_dialog_help_buttons_open_expected_topics(qapp):
    host = _HelpHost()

    relationships_panel = RelationshipsPanel(host)
    assert relationships_panel.help_btn is not None
    relationships_panel.help_btn.click()

    project_panel = ProjectCockpitPanel(host)
    assert project_panel.help_btn is not None
    project_panel.help_btn.click()

    archive_dialog = ArchiveBrowserDialog([], host)
    assert archive_dialog.help_btn is not None
    archive_dialog.help_btn.click()

    assert host.opened == [
        "relationships",
        "projects",
        "archive",
    ]
