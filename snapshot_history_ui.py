from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from auto_backup import backups_dir, delete_restore_point, list_restore_points
from backup_io import import_payload_into_dbfile, read_backup_file
from crash_logging import log_event, log_exception
from context_help import attach_context_help
from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    add_left_aligned_buttons,
    configure_box_layout,
)
from workspace_profiles import WorkspaceProfileManager


class SnapshotHistoryDialog(QDialog):
    def __init__(self, db, workspace_manager: WorkspaceProfileManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._workspace_manager = workspace_manager
        self._switch_workspace_id: str | None = None

        self.setWindowTitle("Snapshot history")
        self.resize(920, 620)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        intro_panel = SectionPanel(
            "Snapshot history",
            "Snapshots are read-only restore points. Restoring always creates "
            "a separate database copy or a new workspace; the current "
            "database is never overwritten in place.",
        )
        self.help_btn = attach_context_help(
            intro_panel,
            "snapshot_history",
            self,
            tooltip="Open help for backups and snapshot history",
        )
        root.addWidget(intro_panel)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Created", "Reason", "Tasks", "Archived", "Size", "File"])
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.currentItemChanged.connect(self._update_details)
        self.tree.itemDoubleClicked.connect(lambda *_: self._restore_to_copy())
        self.tree_stack = EmptyStateStack(
            self.tree,
            "No snapshots available.",
            "Create a backup or wait for an autosnapshot to populate history.",
        )
        intro_panel.body_layout.addWidget(self.tree_stack, 1)

        details_panel = SectionPanel(
            "Snapshot details and actions",
            "Selected snapshot metadata and restore actions stay attached to "
            "the snapshot details area.",
        )
        root.addWidget(details_panel, 1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.open_folder_btn = QPushButton("Open snapshot folder")
        self.restore_btn = QPushButton("Restore to DB copy")
        self.workspace_btn = QPushButton("Create workspace from snapshot")
        self.delete_btn = QPushButton("Delete snapshot")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(
            actions,
            self.refresh_btn,
            self.open_folder_btn,
            self.restore_btn,
            self.workspace_btn,
            self.delete_btn,
            self.close_btn,
            trailing_stretch=False,
        )
        details_panel.body_layout.addLayout(actions)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.details.setMinimumHeight(180)
        self.details_stack = EmptyStateStack(
            self.details,
            "No snapshot selected.",
            "Select a snapshot to inspect its metadata and restore options.",
        )
        details_panel.body_layout.addWidget(self.details_stack, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.restore_btn.clicked.connect(self._restore_to_copy)
        self.workspace_btn.clicked.connect(self._create_workspace_from_snapshot)
        self.delete_btn.clicked.connect(self._delete_snapshot)
        self.close_btn.clicked.connect(self.reject)

        self.refresh()

    def switch_workspace_id(self) -> str | None:
        return self._switch_workspace_id

    def _selected_snapshot(self) -> dict | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        row = item.data(0, Qt.ItemDataRole.UserRole)
        return row if isinstance(row, dict) else None

    def refresh(self):
        selected_path = None
        current = self._selected_snapshot()
        if current:
            selected_path = str(current.get("path") or "")
        self.tree.clear()
        for row in list_restore_points(limit=100, db_path=getattr(self._db, "path", None)):
            item = QTreeWidgetItem(
                [
                    str(row.get("created_at") or ""),
                    str(row.get("reason") or ""),
                    str(row.get("task_count") or "-"),
                    str(row.get("archived_count") or "-"),
                    str(row.get("size_bytes") or 0),
                    str(row.get("filename") or ""),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.tree.addTopLevelItem(item)
            if selected_path and str(row.get("path") or "") == selected_path:
                self.tree.setCurrentItem(item)
        for col in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(col)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount() > 0:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._update_details(self.tree.currentItem(), None)
        self.tree_stack.set_has_content(self.tree.topLevelItemCount() > 0)

    def _update_details(self, current, _previous):
        row = None
        if current is not None:
            row = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(row, dict):
            self.details.setPlainText("No snapshot selected.")
            self.details_stack.set_has_content(False)
            return
        lines = [
            f"File: {str(row.get('path') or '')}",
            f"Created: {str(row.get('created_at') or '')}",
            f"Reason: {str(row.get('reason') or '')}",
            f"Exported at: {str(row.get('exported_at') or '') or '-'}",
            f"Tasks: {str(row.get('task_count') or '-')}",
            f"Archived tasks: {str(row.get('archived_count') or '-')}",
            f"Custom columns: {str(row.get('custom_column_count') or '-')}",
            f"Saved views: {str(row.get('saved_view_count') or '-')}",
            f"Templates: {str(row.get('template_count') or '-')}",
            f"Size (bytes): {str(row.get('size_bytes') or 0)}",
        ]
        self.details.setPlainText("\n".join(lines))
        self.details_stack.set_has_content(True)

    def _open_folder(self):
        path = backups_dir(getattr(self._db, "path", None))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _restore_to_copy(self):
        row = self._selected_snapshot()
        if not row:
            return
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Restore snapshot to database copy",
            "restored_tasks.sqlite3",
            "SQLite DB (*.sqlite3 *.db);;All files (*.*)",
        )
        if not target_path:
            return
        try:
            log_event(
                "Snapshot restore to database copy started",
                context="snapshot.restore_copy",
                db_path=getattr(self._db, "path", None),
                details={"snapshot_path": str(row.get("path") or ""), "target_path": target_path},
            )
            payload = read_backup_file(Path(str(row.get("path") or "")), parent=self)
            report = import_payload_into_dbfile(self, payload, Path(target_path), make_file_backup=True)
        except Exception as e:
            log_exception(e, context="snapshot.restore_copy", db_path=getattr(self._db, "path", None))
            QMessageBox.critical(self, "Snapshot restore failed", str(e))
            return
        log_event(
            "Snapshot restore to database copy completed",
            context="snapshot.restore_copy",
            db_path=target_path,
            details={
                "snapshot_path": str(row.get("path") or ""),
                "target_path": target_path,
                "mode": str(report.mode or ""),
                "imported_tasks": int(report.imported_tasks or 0),
            },
        )
        QMessageBox.information(
            self,
            "Snapshot restored",
            f"Snapshot restored to:\n{target_path}\n\n"
            f"Imported tasks: {int(report.imported_tasks or 0)}\n"
            f"Created columns: {int(report.created_columns or 0)}\n"
            f"Mode: {str(report.mode or '')}",
        )

    def _create_workspace_from_snapshot(self):
        row = self._selected_snapshot()
        if not row:
            return
        default_name = f"Restored {str(row.get('created_at') or '').replace(':', '-').replace(' ', ' ')}".strip()
        name, ok = QInputDialog.getText(self, "Create workspace from snapshot", "Workspace name:", text=default_name)
        if not ok or not str(name or "").strip():
            return
        workspace_id = None
        record = None
        try:
            log_event(
                "Workspace creation from snapshot started",
                context="snapshot.create_workspace",
                db_path=getattr(self._db, "path", None),
                details={"snapshot_path": str(row.get("path") or ""), "workspace_name": str(name).strip()},
            )
            suggested = self._workspace_manager.suggested_db_path(str(name).strip())
            payload = read_backup_file(Path(str(row.get("path") or "")), parent=self)
            record = self._workspace_manager.create_workspace(str(name).strip(), db_path=suggested)
            workspace_id = str(record.get("id") or "")
            report = import_payload_into_dbfile(self, payload, Path(str(record.get("db_path") or "")), make_file_backup=False)
        except Exception as e:
            if workspace_id:
                try:
                    self._workspace_manager.remove_workspace(workspace_id)
                except Exception:
                    pass
            log_exception(e, context="snapshot.create_workspace", db_path=getattr(self._db, "path", None))
            QMessageBox.critical(self, "Workspace creation failed", str(e))
            return
        log_event(
            "Workspace creation from snapshot completed",
            context="snapshot.create_workspace",
            db_path=str(record.get("db_path") or ""),
            details={
                "snapshot_path": str(row.get("path") or ""),
                "workspace_id": str(record.get("id") or ""),
                "workspace_name": str(record.get("name") or ""),
                "imported_tasks": int(report.imported_tasks or 0),
            },
        )

        res = QMessageBox.question(
            self,
            "Workspace created",
            f"Created workspace '{str(record.get('name') or '')}'.\n\n"
            f"Imported tasks: {int(report.imported_tasks or 0)}\n\n"
            "Switch to it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if res == QMessageBox.StandardButton.Yes:
            self._switch_workspace_id = str(record.get("id") or "")
            self.accept()

    def _delete_snapshot(self):
        row = self._selected_snapshot()
        if not row:
            return
        filename = str(row.get("filename") or row.get("path") or "snapshot")
        path = str(row.get("path") or "")
        res = QMessageBox.warning(
            self,
            "Delete snapshot",
            f"Delete snapshot '{filename}'?\n\n"
            "This permanently removes the restore point file and cannot "
            "be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        try:
            log_event(
                "Snapshot deletion started",
                context="snapshot.delete",
                db_path=getattr(self._db, "path", None),
                details={"snapshot_path": path, "filename": filename},
            )
            deleted = delete_restore_point(
                path,
                db_path=getattr(self._db, "path", None),
            )
        except Exception as e:
            log_exception(
                e,
                context="snapshot.delete",
                db_path=getattr(self._db, "path", None),
            )
            QMessageBox.warning(self, "Snapshot deletion failed", str(e))
            return
        log_event(
            "Snapshot deletion completed",
            context="snapshot.delete",
            db_path=getattr(self._db, "path", None),
            details={
                "snapshot_path": str(deleted.get("path") or ""),
                "filename": str(deleted.get("filename") or ""),
            },
        )
        self.refresh()
