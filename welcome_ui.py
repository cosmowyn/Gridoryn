from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from context_help import create_context_help_header
from platform_utils import shortcut_display_text
from ui_layout import add_left_aligned_buttons, configure_box_layout


class WelcomeDialog(QDialog):
    ACTION_EMPTY = "empty"
    ACTION_DEMO = "demo"
    ACTION_DEMO_WORKSPACE = "demo_workspace"
    ACTION_HELP = "help"
    ACTION_REVIEW = "review"

    def __init__(self, can_load_demo: bool, can_create_demo_workspace: bool = True, parent=None):
        super().__init__(parent)
        self._action = self.ACTION_EMPTY

        self.setWindowTitle("Welcome")
        self.resize(760, 520)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        self.help_header = create_context_help_header(
            "Welcome",
            "welcome_dialog",
            self,
            tooltip="Open help for onboarding and quick start",
        )
        root.addWidget(self.help_header)

        intro = QGroupBox("Welcome to CustomTaskManager")
        intro_layout = QVBoxLayout(intro)
        configure_box_layout(intro_layout)
        text = QLabel(
            "Start with Quick add for fast capture, use perspectives to "
            "change context, and use Review Workflow to keep the system "
            "clean. You can also open a dedicated demo workspace without "
            "touching your current data."
        )
        text.setWordWrap(True)
        intro_layout.addWidget(text)
        root.addWidget(intro)

        shortcuts = QGroupBox("Useful starting points")
        shortcuts_layout = QVBoxLayout(shortcuts)
        configure_box_layout(shortcuts_layout)
        shortcuts_text = QLabel(
            "Quick add examples:\n"
            "  Call supplier tomorrow p1\n"
            "  Finish report next week high\n\n"
            "Core shortcuts:\n"
            f"  {shortcut_display_text('Ctrl+L')} focus Quick add\n"
            f"  {shortcut_display_text('Ctrl+F')} focus Search\n"
            f"  {shortcut_display_text('Ctrl+Shift+P')} open Command palette\n"
            "  F1 open Help"
        )
        shortcuts_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        shortcuts_text.setWordWrap(True)
        shortcuts_layout.addWidget(shortcuts_text)
        root.addWidget(shortcuts)

        self.remember = QCheckBox("Do not show this welcome guide automatically again")
        self.remember.setChecked(True)
        self.remember.setToolTip("You can always reopen this guide later from the Help menu.")
        root.addWidget(self.remember)

        actions = QHBoxLayout()
        self.start_empty_btn = QPushButton("Start empty")
        self.start_empty_btn.setToolTip("Close the guide and start with an empty task list.")
        self.demo_btn = QPushButton("Load demo data here")
        self.demo_btn.setToolTip("Insert sample data into the current empty workspace.")
        self.demo_workspace_btn = QPushButton("Open demo workspace")
        self.demo_workspace_btn.setToolTip("Create a separate demo workspace so you can explore features safely.")
        self.help_btn = QPushButton("Open help")
        self.help_btn.setToolTip("Open the embedded guide after closing this dialog.")
        self.review_btn = QPushButton("Open review workflow")
        self.review_btn.setToolTip("Open the review workflow after closing this dialog.")
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.setToolTip("Close the welcome guide.")
        self.demo_btn.setEnabled(bool(can_load_demo))
        if not can_load_demo:
            self.demo_btn.setToolTip("Demo data is only offered when the task list is empty.")
        self.demo_workspace_btn.setEnabled(bool(can_create_demo_workspace))
        add_left_aligned_buttons(
            actions,
            self.start_empty_btn,
            self.demo_btn,
            self.demo_workspace_btn,
            self.help_btn,
            self.review_btn,
            self.cancel_btn,
        )
        root.addLayout(actions)

        self.start_empty_btn.clicked.connect(lambda: self._finish(self.ACTION_EMPTY))
        self.demo_btn.clicked.connect(lambda: self._finish(self.ACTION_DEMO))
        self.demo_workspace_btn.clicked.connect(lambda: self._finish(self.ACTION_DEMO_WORKSPACE))
        self.help_btn.clicked.connect(lambda: self._finish(self.ACTION_HELP))
        self.review_btn.clicked.connect(lambda: self._finish(self.ACTION_REVIEW))
        self.cancel_btn.clicked.connect(self.reject)

    def _finish(self, action: str):
        self._action = str(action or self.ACTION_EMPTY)
        self.accept()

    def action(self) -> str:
        return self._action
