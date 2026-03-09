from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from crash_logging import log_event, log_exception
from context_help import attach_context_help
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
    polish_button_layouts,
)
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

        intro_panel = SectionPanel(
            "Workspace profiles",
            "Workspaces keep local databases explicit. Each workspace points "
            "to one SQLite file and restores its own saved view/layout "
            "preferences when you switch.",
        )
        self.help_btn = attach_context_help(
            intro_panel,
            "workspace_manager",
            self,
            tooltip="Open help for workspace profiles",
        )
        root.addWidget(intro_panel)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._update_details)
        self.list.itemDoubleClicked.connect(lambda *_: self._switch_selected())
        self.list_stack = EmptyStateStack(
            self.list,
            "No workspaces available.",
            "Create a workspace or register an existing database to begin.",
        )
        intro_panel.body_layout.addWidget(self.list_stack, 1)

        details_panel = SectionPanel(
            "Workspace details",
            "Selection details stay attached to the workspace list instead of "
            "appearing as a detached form below it.",
        )
        details_form = QFormLayout()
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
        details_panel.body_layout.addLayout(details_form)
        root.addWidget(details_panel)

        actions_panel = SectionPanel(
            "Workspace actions",
            "Create, register, remove, reveal, or switch without leaving the "
            "workspace manager.",
        )
        root.addWidget(actions_panel)

        actions = QHBoxLayout()
        self.create_btn = QPushButton("Create workspace")
        self.add_existing_btn = QPushButton("Add existing DB")
        self.remove_btn = QPushButton("Remove workspace")
        self.switch_btn = QPushButton("Switch")
        self.reveal_btn = QPushButton("Reveal DB folder")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(
            actions,
            self.create_btn,
            self.add_existing_btn,
            self.remove_btn,
            self.switch_btn,
            self.reveal_btn,
            self.close_btn,
        )
        actions_panel.body_layout.addLayout(actions)

        self.create_btn.clicked.connect(self._create_workspace)
        self.add_existing_btn.clicked.connect(self._add_existing_database)
        self.remove_btn.clicked.connect(self._remove_workspace)
        self.switch_btn.clicked.connect(self._switch_selected)
        self.reveal_btn.clicked.connect(self._reveal_workspace_path)
        self.close_btn.clicked.connect(self.reject)

        polish_button_layouts(self)
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
        self.list_stack.set_has_content(self.list.count() > 0)

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
            self.remove_btn.setEnabled(False)
            self.remove_btn.setToolTip("Select a workspace to remove it.")
            return
        self.lbl_name.setText(str(row.get("name") or row.get("id") or ""))
        self.lbl_path.setText(str(row.get("db_path") or ""))
        self.lbl_created.setText(str(row.get("created_at") or ""))
        self.lbl_opened.setText(str(row.get("last_opened_at") or ""))
        try:
            plan = self._manager.workspace_removal_plan(str(row.get("id") or ""))
        except Exception:
            self.remove_btn.setEnabled(False)
            self.remove_btn.setToolTip("This workspace cannot be removed.")
            return
        self.remove_btn.setEnabled(bool(plan.get("can_remove")))
        tooltip = (
            "Remove the workspace profile or remove the profile and its "
            "database file. This cannot be undone."
        )
        if not plan.get("can_remove"):
            tooltip = str(plan.get("reason") or tooltip)
        elif not plan.get("can_delete_db_file"):
            tooltip = (
                "Remove the workspace profile. The database file will stay "
                "because it is shared, active, or missing."
            )
        self.remove_btn.setToolTip(tooltip)

    def _create_workspace(self):
        name, ok = QInputDialog.getText(self, "Create workspace", "Workspace name:")
        if not ok or not str(name or "").strip():
            return
        try:
            row = self._manager.create_workspace(str(name).strip())
        except Exception as e:
            log_exception(e, context="workspace.create")
            QMessageBox.warning(self, "Workspace creation failed", str(e))
            return
        log_event(
            "Workspace created",
            context="workspace.create",
            db_path=str(row.get("db_path") or ""),
            details={"workspace_id": str(row.get("id") or ""), "workspace_name": str(row.get("name") or "")},
        )
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
            log_exception(e, context="workspace.register_existing", db_path=path)
            QMessageBox.warning(self, "Workspace registration failed", str(e))
            return
        log_event(
            "Existing database registered as workspace",
            context="workspace.register_existing",
            db_path=path,
            details={"workspace_id": str(row.get("id") or ""), "workspace_name": str(row.get("name") or "")},
        )
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
        log_event(
            "Workspace switch selected from manager",
            context="workspace.switch.select",
            details={"workspace_id": workspace_id},
        )
        self._switch_workspace_id = workspace_id
        self.accept()

    def _remove_workspace(self):
        row = self._selected_workspace()
        if not row:
            return
        workspace_id = str(row.get("id") or "")
        name = str(row.get("name") or workspace_id or "")
        try:
            plan = self._manager.workspace_removal_plan(workspace_id)
        except Exception as e:
            log_exception(e, context="workspace.remove.plan")
            QMessageBox.warning(self, "Workspace removal failed", str(e))
            return

        if not plan.get("can_remove"):
            QMessageBox.information(
                self,
                "Workspace cannot be removed",
                str(plan.get("reason") or "This workspace cannot be removed."),
            )
            return

        delete_db_file = False
        if plan.get("can_delete_db_file"):
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Remove workspace")
            msg_box.setText(
                f"Remove workspace '{name}'?\n\n"
                "This action cannot be undone."
            )
            msg_box.setInformativeText(
                "You can remove only the workspace profile, or remove the "
                "profile and permanently delete its SQLite database file."
            )
            profile_btn = msg_box.addButton(
                "Remove profile only",
                QMessageBox.ButtonRole.AcceptRole,
            )
            delete_btn = msg_box.addButton(
                "Remove profile and DB",
                QMessageBox.ButtonRole.DestructiveRole,
            )
            cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
            msg_box.exec()
            clicked = msg_box.clickedButton()
            if clicked == cancel_btn:
                return
            delete_db_file = clicked == delete_btn
            if clicked not in (profile_btn, delete_btn):
                return
        else:
            res = QMessageBox.warning(
                self,
                "Remove workspace",
                f"Remove workspace '{name}'?\n\n"
                "This action cannot be undone.\n\n"
                "The database file will be kept because it is shared, "
                "active, or missing.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if res != QMessageBox.StandardButton.Yes:
                return

        try:
            log_event(
                "Workspace removal started",
                context="workspace.remove",
                db_path=str(row.get("db_path") or ""),
                details={
                    "workspace_id": workspace_id,
                    "workspace_name": name,
                    "delete_db_file": delete_db_file,
                },
            )
            report = self._manager.remove_workspace(
                workspace_id,
                delete_db_file=delete_db_file,
            )
        except Exception as e:
            log_exception(
                e,
                context="workspace.remove",
                db_path=str(row.get("db_path") or ""),
            )
            QMessageBox.warning(self, "Workspace removal failed", str(e))
            return

        log_event(
            "Workspace removal completed",
            context="workspace.remove",
            db_path=str(report.get("db_path") or ""),
            details={
                "workspace_id": workspace_id,
                "workspace_name": name,
                "deleted_db_file": bool(report.get("deleted_db_file")),
            },
        )
        self.refresh()
