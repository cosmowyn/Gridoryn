from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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


@dataclass
class PaletteCommand:
    command_id: str
    title: str
    subtitle: str = ""
    keywords: tuple[str, ...] = ()
    action: Callable[[], None] | None = None

    def haystack(self) -> str:
        parts = [self.title, self.subtitle, " ".join(self.keywords)]
        return " ".join(p for p in parts if p).lower()


class CommandPaletteDialog(QDialog):
    def __init__(self, commands: list[PaletteCommand], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.resize(760, 460)

        self._commands = list(commands or [])

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        intro = QLabel("Search commands and press Enter to execute the selected action.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        top = QFormLayout()
        configure_form_layout(top, label_width=90)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to search commands…")
        self.search.setToolTip("Search by command title, alias, or workflow keyword.")
        add_form_row(top, "Command", self.search)
        root.addLayout(top)

        self.list = QListWidget()
        self.list.setToolTip("Press Enter to run selected command.")
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(btn_row, self.run_btn, self.close_btn)
        root.addLayout(btn_row)

        self.search.textChanged.connect(self._rebuild)
        self.run_btn.clicked.connect(self._accept_if_has_selection)
        self.close_btn.clicked.connect(self.reject)
        self.list.itemActivated.connect(lambda *_: self._accept_if_has_selection())
        self.list.itemDoubleClicked.connect(lambda *_: self._accept_if_has_selection())

        self._rebuild()
        self.search.setFocus()

    def _matches(self, cmd: PaletteCommand, text: str) -> bool:
        q = str(text or "").strip().lower()
        if not q:
            return True
        tokens = [t for t in q.split() if t]
        hay = cmd.haystack()
        return all(tok in hay for tok in tokens)

    def _rebuild(self):
        q = self.search.text()
        self.list.clear()
        for cmd in self._commands:
            if not self._matches(cmd, q):
                continue
            label = cmd.title
            if cmd.subtitle:
                label = f"{cmd.title}    —    {cmd.subtitle}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cmd.command_id)
            item.setToolTip(cmd.subtitle or cmd.title)
            self.list.addItem(item)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)
            self.run_btn.setEnabled(True)
        else:
            self.run_btn.setEnabled(False)

    def _accept_if_has_selection(self):
        if self.selected_command_id() is None:
            return
        self.accept()

    def selected_command_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        cid = item.data(Qt.ItemDataRole.UserRole)
        if not cid:
            return None
        return str(cid)
