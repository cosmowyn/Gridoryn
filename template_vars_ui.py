from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from context_help import attach_context_help
from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    EmptyStateStack,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
    polish_button_layouts,
)


class TemplateVariablesDialog(QDialog):
    def __init__(self, variables: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Template Variables")
        self.setModal(True)
        self.resize(520, 320)

        self._edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        section = SectionPanel(
            "Template values",
            "Fill in placeholder values before inserting the template.",
        )
        self.help_btn = attach_context_help(
            section,
            "template_variables_dialog",
            self,
            tooltip="Open help for templates and variables",
        )
        section.setToolTip(
            "Provide values for template placeholders. Placeholder names "
            "containing 'date' default to today's ISO date."
        )
        root.addWidget(section, 1)

        form_container = QWidget()
        form_container_layout = QVBoxLayout(form_container)
        configure_box_layout(form_container_layout)

        form = QFormLayout()
        configure_form_layout(form, label_width=140)
        form_container_layout.addLayout(form)

        for name in variables:
            e = QLineEdit()
            e.setPlaceholderText(f"Value for {{{name}}}")
            if "date" in name.lower() and e.text().strip() == "":
                e.setText(datetime.now().date().isoformat())
            add_form_row(form, f"{{{name}}}", e)
            self._edits[str(name)] = e

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.form_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.form_scroll.setWidget(form_container)

        self.form_stack = EmptyStateStack(
            self.form_scroll,
            "No template variables",
            "This template does not require any values. You can insert it directly.",
        )
        self.form_stack.set_has_content(bool(variables))
        section.body_layout.addWidget(self.form_stack, 1)

        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Insert template")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(btns, self.apply_btn, self.cancel_btn)
        section.body_layout.addLayout(btns)

        self.apply_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        if variables:
            self._edits[variables[0]].setFocus()
        polish_button_layouts(self)

    def values(self) -> dict[str, str]:
        out = {}
        for name, edit in self._edits.items():
            out[str(name)] = str(edit.text() or "").strip()
        return out
