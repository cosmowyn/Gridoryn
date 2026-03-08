from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    add_left_aligned_buttons,
    configure_box_layout,
)


class FocusPanel(QWidget):
    refreshRequested = Signal(bool)
    focusTaskRequested = Signal(int)
    openDetailsRequested = Signal(int)
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        intro_panel = SectionPanel(
            "Focus mode",
            "Keep a compact, low-friction work list without leaving the main "
            "tree-driven workflow.",
        )
        self.intro = QLabel(
            "Focus mode surfaces overdue work, today work, and next actionable tasks. "
            "Use it as a short list for the current session without replacing the main tree."
        )
        self.intro.setWordWrap(True)
        intro_panel.body_layout.addWidget(self.intro)

        self.current_task = QLabel("Current selection: none")
        self.current_task.setWordWrap(True)
        self.current_task.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        intro_panel.body_layout.addWidget(self.current_task)
        root.addWidget(intro_panel)

        list_panel = SectionPanel(
            "Focus list",
            "Controls stay attached to the list they affect so focused work "
            "does not turn into panel-hunting.",
        )
        root.addWidget(list_panel, 1)

        controls = QHBoxLayout()
        configure_box_layout(controls, margins=(0, 0, 0, 0), spacing=8)
        self.include_waiting = QCheckBox("Include blocked/waiting context")
        self.include_waiting.setToolTip(
            "Also show due-today blocked or waiting tasks in the focus list."
        )
        self.refresh_btn = QPushButton("Refresh focus")
        self.refresh_btn.setToolTip("Rebuild the focus list using the current focus options.")
        self.focus_btn = QPushButton("Focus task")
        self.focus_btn.setToolTip("Jump to the selected focus item in the main tree.")
        self.details_btn = QPushButton("Open details")
        self.details_btn.setToolTip("Open the details panel for the selected focus item.")
        self.close_btn = QPushButton("Exit focus mode")
        self.close_btn.setToolTip("Hide the focus-mode dock.")
        add_left_aligned_buttons(
            controls,
            self.include_waiting,
            self.refresh_btn,
            self.focus_btn,
            self.details_btn,
            self.close_btn,
            trailing_stretch=False,
        )
        list_panel.body_layout.addLayout(controls)

        self.list = QListWidget()
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setToolTip(
            "Actionable focus list. Double-click an item to focus it in the task tree."
        )
        self.list_stack = EmptyStateStack(
            self.list,
            "No focus items right now.",
            "Refresh focus after selecting a task or as due work becomes available.",
        )
        list_panel.body_layout.addWidget(self.list_stack, 1)

        self.refresh_btn.clicked.connect(
            lambda: self.refreshRequested.emit(
                self.include_waiting.isChecked()
            )
        )
        self.list.itemDoubleClicked.connect(self._emit_focus_from_item)
        self.focus_btn.clicked.connect(self._emit_focus)
        self.details_btn.clicked.connect(self._emit_open_details)
        self.close_btn.clicked.connect(self.closeRequested.emit)

    def sizeHint(self) -> QSize:
        return QSize(440, 520)

    def minimumSizeHint(self) -> QSize:
        return QSize(340, 380)

    def selected_task_id(self) -> int | None:
        item = self.list.currentItem()
        if item is None:
            return None
        try:
            task_id = int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            return None
        return task_id if task_id > 0 else None

    def _emit_focus_from_item(self, item: QListWidgetItem):
        if item is None:
            return
        try:
            task_id = int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            return
        if task_id > 0:
            self.focusTaskRequested.emit(task_id)

    def _emit_focus(self):
        task_id = self.selected_task_id()
        if task_id is not None:
            self.focusTaskRequested.emit(task_id)

    def _emit_open_details(self):
        task_id = self.selected_task_id()
        if task_id is not None:
            self.openDetailsRequested.emit(task_id)

    def set_current_summary(
        self,
        current_summary: str,
        current_task_id: int | None = None,
    ):
        self.current_task.setText(current_summary or "Current selection: none")
        if current_task_id is None:
            return
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is None:
                continue
            try:
                task_id = int(item.data(Qt.ItemDataRole.UserRole))
            except Exception:
                continue
            if task_id == int(current_task_id):
                self.list.setCurrentRow(row)
                break

    def set_focus_data(
        self,
        rows: list[dict],
        current_summary: str,
        current_task_id: int | None = None,
    ):
        self.list.clear()
        for row in rows or []:
            section = str(row.get("focus_section") or "Task")
            desc = str(row.get("description") or "")
            due = str(row.get("due_date") or "-")
            prio = str(row.get("priority") or "")
            note = str(row.get("focus_note") or "")
            text = f"[{section}] [P{prio}] {desc} | due: {due}"
            if note:
                text += f" | {note}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
            self.list.addItem(item)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)
        self.list_stack.set_has_content(self.list.count() > 0)
        self.set_current_summary(current_summary, current_task_id)
