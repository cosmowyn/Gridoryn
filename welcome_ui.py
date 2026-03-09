from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_metadata import APP_NAME
from context_help import create_context_help_header
from platform_utils import shortcut_display_text
from ui_layout import (
    add_left_aligned_buttons,
    configure_box_layout,
    polish_button_layouts,
)


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
        self.resize(980, 760)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        self.help_header = create_context_help_header(
            "Welcome",
            "welcome_dialog",
            self,
            tooltip="Open help for onboarding and quick start",
        )
        root.addWidget(self.help_header)

        intro = QGroupBox(f"Welcome to {APP_NAME}")
        intro_layout = QVBoxLayout(intro)
        configure_box_layout(intro_layout)
        text = QLabel(
            "Start with Quick add for fast capture, use perspectives to "
            "change context, and use Review Workflow to keep the system "
            "clean. You can also open a dedicated full-featured demo "
            "workspace without touching your current data."
        )
        text.setWordWrap(True)
        intro_layout.addWidget(text)
        root.addWidget(intro)

        screenshots = self._build_screenshot_panel()
        if screenshots is not None:
            root.addWidget(screenshots)

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
        self.demo_btn.setToolTip(
            "Insert the full showcase demo set into the current empty workspace."
        )
        self.demo_workspace_btn = QPushButton("Open demo workspace")
        self.demo_workspace_btn.setToolTip(
            "Create a separate full-featured demo workspace so you can explore "
            "features safely."
        )
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
        polish_button_layouts(self)

    def _build_screenshot_panel(self) -> QWidget | None:
        screenshot_specs = [
            ("Main workspace", "docs/screenshots/main-workspace.png"),
            ("Project cockpit timeline", "docs/screenshots/project-cockpit-timeline.png"),
            ("Review workflow", "docs/screenshots/review-workflow.png"),
            ("Relationship inspector", "docs/screenshots/relationship-inspector.png"),
        ]
        available = []
        base_dir = Path(__file__).resolve().parent
        for title, rel_path in screenshot_specs:
            path = base_dir / rel_path
            if path.exists():
                available.append((title, path))
        if not available:
            return None

        panel = QGroupBox("See the workspace")
        layout = QGridLayout(panel)
        configure_box_layout(layout, margins=(8, 8, 8, 8), spacing=8)

        for idx, (title, path) in enumerate(available):
            cell = QWidget(panel)
            cell_layout = QVBoxLayout(cell)
            configure_box_layout(cell_layout, margins=(0, 0, 0, 0), spacing=4)

            preview = QLabel(cell)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setToolTip(str(path))
            preview.setMinimumSize(220, 130)
            preview.setMaximumHeight(150)
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                preview.setPixmap(
                    pixmap.scaled(
                        320,
                        150,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                preview.setText(title)

            caption = QLabel(title, cell)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)

            cell_layout.addWidget(preview)
            cell_layout.addWidget(caption)
            layout.addWidget(cell, idx // 2, idx % 2)

        return panel

    def _finish(self, action: str):
        self._action = str(action or self.ACTION_EMPTY)
        self.accept()

    def action(self) -> str:
        return self._action
