from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QListWidget, QListWidgetItem, QFormLayout
)

from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    EmptyStateStack,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
    form_label,
)


class AddColumnDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add custom column")
        self.resize(460, 180)

        v = QVBoxLayout(self)
        configure_box_layout(v, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        section = SectionPanel(
            "Custom column definition",
            "Add a reusable custom field to tasks in this workspace.",
        )
        v.addWidget(section, 1)

        intro = QLabel(
            "Choose the field name and type. List columns can define starting values."
        )
        intro.setWordWrap(True)
        section.body_layout.addWidget(intro)

        form = QFormLayout()
        configure_form_layout(form, label_width=100)
        section.body_layout.addLayout(form)

        self.name = QLineEdit()
        add_form_row(form, "Name", self.name)

        self.typ = QComboBox()
        self.typ.addItems(["text", "int", "date", "bool", "list"])
        add_form_row(form, "Type", self.typ)

        self._list_label = form_label("List values", 100)
        self.list_values = QLineEdit()
        self.list_values.setPlaceholderText("Comma-separated values (optional)")
        form.addRow(self._list_label, self.list_values)

        self.typ.currentTextChanged.connect(self._update_type_ui)
        self._update_type_ui(self.typ.currentText())

        btns = QHBoxLayout()
        ok = QPushButton("Add")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        add_left_aligned_buttons(btns, ok, cancel)
        section.body_layout.addLayout(btns)

    def _update_type_ui(self, col_type: str):
        is_list = str(col_type) == "list"
        self._list_label.setVisible(is_list)
        self.list_values.setVisible(is_list)

    def result_value(self):
        raw = self.list_values.text().strip()
        values = []
        if raw:
            seen = set()
            for part in raw.split(","):
                s = part.strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                values.append(s)
        return self.name.text().strip(), self.typ.currentText(), values


class RemoveColumnDialog(QDialog):
    def __init__(self, columns: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove custom column")
        self.resize(420, 320)
        self.columns = columns

        v = QVBoxLayout(self)
        configure_box_layout(v, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        section = SectionPanel(
            "Available custom columns",
            "Removing a custom column also removes its stored values.",
        )
        v.addWidget(section, 1)

        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for c in columns:
            item = QListWidgetItem(f"{c['name']}  ({c['col_type']})")
            item.setData(32, int(c["id"]))
            self.list.addItem(item)
        self.list_stack = EmptyStateStack(
            self.list,
            "No custom columns",
            "There are no custom columns to remove right now.",
        )
        self.list_stack.set_has_content(bool(columns))
        section.body_layout.addWidget(self.list_stack, 1)

        btns = QHBoxLayout()
        self.ok = QPushButton("Remove")
        cancel = QPushButton("Cancel")
        self.ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self.ok.setEnabled(bool(columns))
        add_left_aligned_buttons(btns, self.ok, cancel)
        section.body_layout.addLayout(btns)

    def selected_column_id(self):
        it = self.list.currentItem()
        return int(it.data(32)) if it else None
