from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    add_left_aligned_buttons,
    configure_box_layout,
    polish_button_layouts,
)


class QuickCaptureDialog(QDialog):
    captureRequested = Signal(str)
    revealRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Capture")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(520, 140)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        self.intro = QLabel(
            "Capture a task or command quickly. Examples: Call supplier @work !p1 /today, "
            "move this to next friday, show blocked tasks."
        )
        self.intro.setWordWrap(True)
        root.addWidget(self.intro)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Quick capture…")
        self.input.returnPressed.connect(self._emit_capture)
        root.addWidget(self.input)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("QuickCaptureStatus")
        root.addWidget(self.status)

        actions = QHBoxLayout()
        self.capture_btn = QPushButton("Capture")
        self.show_app_btn = QPushButton("Show app")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(actions, self.capture_btn, self.show_app_btn, self.close_btn)
        root.addLayout(actions)

        self.capture_btn.clicked.connect(self._emit_capture)
        self.show_app_btn.clicked.connect(self.revealRequested.emit)
        self.close_btn.clicked.connect(self.hide)
        polish_button_layouts(self)

    def _emit_capture(self):
        text = self.input.text().strip()
        if not text:
            return
        self.captureRequested.emit(text)

    def set_feedback(self, text: str, ok: bool = True):
        message = str(text or "").strip()
        self.status.setText(message)
        color = "#2d6a4f" if ok else "#b42318"
        self.status.setStyleSheet(f"color: {color};")

    def capture_succeeded(self, text: str = "Captured."):
        self.set_feedback(text, ok=True)
        self.input.clear()
        self.input.setFocus()
        self.input.selectAll()

    def capture_failed(self, text: str):
        self.set_feedback(text, ok=False)
        self.input.setFocus()
        self.input.selectAll()
