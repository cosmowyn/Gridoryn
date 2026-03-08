from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from crash_logging import (
    current_log_path,
    list_log_paths,
    logs_dir,
    read_log_text,
)
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    add_left_aligned_buttons,
    configure_box_layout,
)


class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application log")
        self.resize(980, 700)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        intro_panel = SectionPanel(
            "Application log",
            "This log includes unexpected exceptions and labeled high-risk "
            "operations such as backups, imports, workspace switches, "
            "repairs, and snapshot restores.",
        )
        root.addWidget(intro_panel)

        top = QHBoxLayout()
        configure_box_layout(top, margins=(0, 0, 0, 0), spacing=8)
        top.addWidget(QLabel("Log file"))
        self.file_combo = QComboBox()
        self.file_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
        self.file_combo.currentIndexChanged.connect(self._load_selected)
        self.file_combo.setToolTip("Choose which log file to view.")
        top.addWidget(self.file_combo, 1)
        intro_panel.body_layout.addLayout(top)

        self.path_label = QLabel("")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        intro_panel.body_layout.addWidget(self.path_label)

        content_panel = SectionPanel(
            "Log contents",
            "The selected log opens below, with file-level actions attached to "
            "the viewer instead of detached at the dialog edge.",
        )
        root.addWidget(content_panel, 1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.open_file_btn = QPushButton("Open file")
        self.open_folder_btn = QPushButton("Open log folder")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(
            actions,
            self.refresh_btn,
            self.open_file_btn,
            self.open_folder_btn,
            self.close_btn,
            trailing_stretch=False,
        )
        content_panel.body_layout.addLayout(actions)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text.setToolTip("Application log contents.")
        self.text_stack = EmptyStateStack(
            self.text,
            "No log file selected.",
            "Choose a log file from the drop-down to inspect application events.",
        )
        content_panel.body_layout.addWidget(self.text_stack, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        self.open_file_btn.clicked.connect(self._open_selected_file)
        self.open_folder_btn.clicked.connect(self._open_logs_folder)
        self.close_btn.clicked.connect(self.accept)

        self.refresh()

    def refresh(self):
        selected_path = self.selected_log_path()
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        paths = list_log_paths(limit=50)
        if not paths:
            fallback = current_log_path()
            self.file_combo.addItem(fallback.name, str(fallback))
        else:
            for path in paths:
                self.file_combo.addItem(path.name, str(path))
        self.file_combo.blockSignals(False)

        if selected_path:
            idx = self.file_combo.findData(selected_path)
            if idx >= 0:
                self.file_combo.setCurrentIndex(idx)
                self._load_selected()
                return
        if self.file_combo.count() > 0:
            self.file_combo.setCurrentIndex(0)
        self._load_selected()

    def selected_log_path(self) -> str:
        return str(self.file_combo.currentData() or "").strip()

    def _load_selected(self):
        raw = self.selected_log_path()
        self.path_label.setText(raw)
        if not raw:
            self.text.setPlainText("No log file selected.")
            self.text_stack.set_has_content(False)
            return
        path = Path(raw)
        if not path.exists():
            self.text.setPlainText("The selected log file does not exist yet.")
            self.text_stack.set_has_content(False)
            return
        self.text.setPlainText(read_log_text(path))
        self.text.moveCursor(QTextCursor.MoveOperation.End)
        self.text_stack.set_has_content(bool(self.text.toPlainText().strip()))

    def _open_selected_file(self):
        raw = self.selected_log_path()
        if not raw:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(raw))

    def _open_logs_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))
