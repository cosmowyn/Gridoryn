from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ui_layout import add_form_row, add_left_aligned_buttons, configure_box_layout, configure_form_layout
from workspace_profiles import WorkspaceProfileManager


class WorkspaceManagerDialog(QDialog):
    def __init__(self, manager: WorkspaceProfileManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._switch_workspace_id: str | None = None

        self.setWindowTitle("Workspace profiles")
        self.resize(760, 480)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        intro = QLabel(
            "Workspaces keep task databases explicit. Each workspace points to one SQLite file and restores its own "
            "saved view/layout preferences when you switch."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._update_details)
        self.list.itemDoubleClicked.connect(lambda *_: self._switch_selected())
        root.addWidget(self.list, 1)

        details_group = QGroupBox("Workspace details")
        details_form = QFormLayout(details_group)
        configure_form_layout(details_form, label_width=170)
        self.lbl_name = QLabel("-")
        self.lbl_path = QLabel("-")
        self.lbl_created = QLabel("-")
        self.lbl_opened = QLabel("-")
        for label in (self.lbl_name, self.lbl_path, self.lbl_created, self.lbl_opened):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        add_form_row(details_form, "Workspace", self.lbl_name)
        add_form_row(details_form, "Database path", self.lbl_path)
        add_form_row(details_form, "Created", self.lbl_created)
        add_form_row(details_form, "Last opened", self.lbl_opened)
        root.addWidget(details_group)

        actions = QHBoxLayout()
        self.create_btn = QPushButton("Create workspace")
        self.add_existing_btn = QPushButton("Add existing DB")
        self.switch_btn = QPushButton("Switch")
        self.reveal_btn = QPushButton("Reveal DB folder")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(
            actions,
            self.create_btn,
            self.add_existing_btn,
            self.switch_btn,
            self.reveal_btn,
            self.close_btn,
        )
        root.addLayout(actions)

        self.create_btn.clicked.connect(self._create_workspace)
        self.add_existing_btn.clicked.connect(self._add_existing_database)
        self.switch_btn.clicked.connect(self._switch_selected)
        self.reveal_btn.clicked.connect(self._reveal_workspace_path)
        self.close_btn.clicked.connect(self.reject)

        self.refresh()

    def refresh(self):
        selected_id = self.selected_workspace_id()
        self.list.clear()
        for row in self._manager.list_workspaces():
            name = str(row.get("name") or row.get("id") or "")
            label = f"{name}  [current]" if row.get("is_current") else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(row.get("id") or ""))
            self.list.addItem(item)
            if selected_id and selected_id == str(row.get("id") or ""):
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count() > 0:
            self.list.setCurrentRow(0)
        self._update_details(self.list.currentItem(), None)

    def selected_workspace_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        return value or None

    def switch_workspace_id(self) -> str | None:
        return self._switch_workspace_id

    def _selected_workspace(self) -> dict | None:
        workspace_id = self.selected_workspace_id()
        if not workspace_id:
            return None
        return self._manager.workspace_by_id(workspace_id)

    def _update_details(self, current, _previous):
        workspace_id = None
        if current is not None:
            workspace_id = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        row = self._manager.workspace_by_id(workspace_id or "")
        if not row:
            self.lbl_name.setText("-")
            self.lbl_path.setText("-")
            self.lbl_created.setText("-")
            self.lbl_opened.setText("-")
            return
        self.lbl_name.setText(str(row.get("name") or row.get("id") or ""))
        self.lbl_path.setText(str(row.get("db_path") or ""))
        self.lbl_created.setText(str(row.get("created_at") or ""))
        self.lbl_opened.setText(str(row.get("last_opened_at") or ""))

    def _create_workspace(self):
        name, ok = QInputDialog.getText(self, "Create workspace", "Workspace name:")
        if not ok or not str(name or "").strip():
            return
        try:
            row = self._manager.create_workspace(str(name).strip())
        except Exception as e:
            QMessageBox.warning(self, "Workspace creation failed", str(e))
            return
        self.refresh()
        target_id = str(row.get("id") or "")
        for i in range(self.list.count()):
            item = self.list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == target_id:
                self.list.setCurrentItem(item)
                break

    def _add_existing_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select workspace database",
            "",
            "SQLite DB (*.sqlite3 *.db);;All files (*.*)",
        )
        if not path:
            return
        default_name = Path(path).stem.replace("_", " ").strip().title() or "Workspace"
        name, ok = QInputDialog.getText(self, "Add existing database", "Workspace name:", text=default_name)
        if not ok or not str(name or "").strip():
            return
        try:
            row = self._manager.create_workspace(str(name).strip(), db_path=path)
        except Exception as e:
            QMessageBox.warning(self, "Workspace registration failed", str(e))
            return
        self.refresh()
        target_id = str(row.get("id") or "")
        for i in range(self.list.count()):
            item = self.list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == target_id:
                self.list.setCurrentItem(item)
                break

    def _reveal_workspace_path(self):
        row = self._selected_workspace()
        if not row:
            return
        db_path = Path(str(row.get("db_path") or "")).expanduser()
        target = db_path.parent if db_path.parent.exists() else db_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _switch_selected(self):
        workspace_id = self.selected_workspace_id()
        if not workspace_id:
            return
        self._switch_workspace_id = workspace_id
        self.accept()
