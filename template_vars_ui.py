from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
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

        intro = QLabel("Fill template placeholder values.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        configure_form_layout(form, label_width=140)
        root.addLayout(form)

        for name in variables:
            e = QLineEdit()
            e.setPlaceholderText(f"Value for {{{name}}}")
            if "date" in name.lower() and e.text().strip() == "":
                e.setText(datetime.now().date().isoformat())
            add_form_row(form, f"{{{name}}}", e)
            self._edits[str(name)] = e

        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Insert template")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(btns, self.apply_btn, self.cancel_btn)
        root.addLayout(btns)

        self.apply_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        if variables:
            self._edits[variables[0]].setFocus()

    def values(self) -> dict[str, str]:
        out = {}
        for name, edit in self._edits.items():
            out[str(name)] = str(edit.text() or "").strip()
        return out
