from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from auto_backup import create_versioned_backup
from crash_logging import log_event, log_exception
from diagnostics import build_diagnostics_report
from ui_layout import add_form_row, add_left_aligned_buttons, configure_box_layout, configure_form_layout


class DiagnosticsDialog(QDialog):
    def __init__(self, db, theme_name_provider, workspace_name_provider=None, workspace_path_provider=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._theme_name_provider = theme_name_provider
        self._workspace_name_provider = workspace_name_provider or (lambda: "")
        self._workspace_path_provider = workspace_path_provider or (lambda: "")
        self._report: dict | None = None

        self.setWindowTitle("Diagnostics")
        self.resize(860, 640)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        summary_group = QGroupBox("Environment")
        summary_form = QFormLayout(summary_group)
        configure_form_layout(summary_form, label_width=190)
        self.lbl_version = QLabel("-")
        self.lbl_schema = QLabel("-")
        self.lbl_theme = QLabel("-")
        self.lbl_profile = QLabel("-")
        self.lbl_db_path = QLabel("-")
        self.lbl_workspace = QLabel("-")
        self.lbl_backups = QLabel("-")
        self.lbl_logs = QLabel("-")
        for lbl in (
            self.lbl_version,
            self.lbl_schema,
            self.lbl_theme,
            self.lbl_profile,
            self.lbl_db_path,
            self.lbl_workspace,
            self.lbl_backups,
            self.lbl_logs,
        ):
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
        add_form_row(summary_form, "App version", self.lbl_version)
        add_form_row(summary_form, "Schema version", self.lbl_schema)
        add_form_row(summary_form, "Current theme", self.lbl_theme)
        add_form_row(summary_form, "Profile", self.lbl_profile)
        add_form_row(summary_form, "Database path", self.lbl_db_path)
        add_form_row(summary_form, "Workspace path", self.lbl_workspace)
        add_form_row(summary_form, "Restore points", self.lbl_backups)
        add_form_row(summary_form, "Log folder", self.lbl_logs)
        root.addWidget(summary_group)

        checks_group = QGroupBox("Checks")
        checks_layout = QVBoxLayout(checks_group)
        configure_box_layout(checks_layout)
        self.checks_list = QListWidget()
        self.checks_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.checks_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.checks_list.currentItemChanged.connect(self._on_check_selected)
        checks_layout.addWidget(self.checks_list)
        root.addWidget(checks_group, 1)

        details_group = QGroupBox("Details")
        details_layout = QVBoxLayout(details_group)
        configure_box_layout(details_layout)
        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.details_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        details_layout.addWidget(self.details_text, 1)
        root.addWidget(details_group, 1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.preview_btn = QPushButton("Preview repairs")
        self.repair_btn = QPushButton("Repair issues")
        self.open_logs_btn = QPushButton("Open log folder")
        self.open_workspace_btn = QPushButton("Open data folder")
        self.close_btn = QPushButton("Close")
        add_left_aligned_buttons(
            actions,
            self.refresh_btn,
            self.preview_btn,
            self.repair_btn,
            self.open_logs_btn,
            self.open_workspace_btn,
            self.close_btn,
        )
        root.addLayout(actions)

        self.refresh_btn.clicked.connect(self.refresh_report)
        self.preview_btn.clicked.connect(self._show_repair_preview)
        self.repair_btn.clicked.connect(self._run_repairs)
        self.open_logs_btn.clicked.connect(lambda: self._open_path(self.lbl_logs.text()))
        self.open_workspace_btn.clicked.connect(lambda: self._open_path(self.lbl_workspace.text()))
        self.close_btn.clicked.connect(self.accept)

        self.refresh_report()

    def refresh_report(self):
        theme_name = ""
        workspace_name = ""
        workspace_path = ""
        try:
            theme_name = str(self._theme_name_provider() or "")
        except Exception:
            theme_name = ""
        try:
            workspace_name = str(self._workspace_name_provider() or "")
        except Exception:
            workspace_name = ""
        try:
            workspace_path = str(self._workspace_path_provider() or "")
        except Exception:
            workspace_path = ""
        self._report = build_diagnostics_report(
            self._db,
            theme_name,
            workspace_name=workspace_name,
            workspace_path=workspace_path,
        )
        report = self._report

        self.lbl_version.setText(f"{report['app_name']} v{report['app_version']}")
        schema_text = str(report["schema_version"])
        if not report.get("schema_ok", False):
            schema_text += " (validation issues)"
        self.lbl_schema.setText(schema_text)
        self.lbl_theme.setText(str(report.get("theme_name") or ""))
        self.lbl_profile.setText(str(report.get("profile") or ""))
        self.lbl_db_path.setText(str(report.get("db_path") or ""))
        self.lbl_workspace.setText(str(report.get("workspace_path") or ""))

        latest = report.get("latest_snapshot")
        restore_points = report.get("restore_points") or []
        if latest:
            self.lbl_backups.setText(
                f"{len(restore_points)} snapshot(s), latest: {latest.get('filename')} @ {latest.get('created_at')}"
            )
        else:
            self.lbl_backups.setText("No restore points found")
        self.lbl_logs.setText(str(report.get("logs_dir") or ""))

        self.checks_list.clear()
        for item in report.get("items") or []:
            prefix = {
                "ok": "[OK]",
                "warning": "[WARN]",
                "error": "[ERROR]",
            }.get(item.status, "[INFO]")
            lw_item = QListWidgetItem(f"{prefix} {item.label}: {item.message}")
            lw_item.setData(Qt.ItemDataRole.UserRole, item)
            self.checks_list.addItem(lw_item)
        if self.checks_list.count() > 0:
            self.checks_list.setCurrentRow(0)
        else:
            self.details_text.setPlainText("No diagnostics available.")

    def _on_check_selected(self, current, _previous):
        if current is None:
            self.details_text.setPlainText("")
            return
        item = current.data(Qt.ItemDataRole.UserRole)
        if item is None:
            self.details_text.setPlainText(current.text())
            return
        text = f"{item.label}\nStatus: {item.status}\n\n{item.message}"
        if item.details:
            text += f"\n\n{item.details}"
        self.details_text.setPlainText(text)

    def _show_repair_preview(self):
        report = self._report or {}
        preview = ((report.get("integrity") or {}).get("repair_preview") or {})
        lines = [
            f"Broken parent links to reset: {int(preview.get('reset_broken_parent_links') or 0)}",
            f"Sibling groups to normalize: {int(preview.get('normalize_sort_order_groups') or 0)}",
            f"Orphaned custom values to delete: {int(preview.get('delete_orphaned_custom_values') or 0)}",
            f"Recurrence records to repair: {int(preview.get('repair_recurrence_records') or 0)}",
            f"Project-management records to repair: {int(preview.get('repair_project_management_records') or 0)}",
        ]
        self.details_text.setPlainText("Repair preview\n\n" + "\n".join(lines))

    def _run_repairs(self):
        report = self._report or {}
        preview = ((report.get("integrity") or {}).get("repair_preview") or {})
        total = sum(int(v or 0) for v in preview.values())
        if total <= 0:
            QMessageBox.information(self, "No repairs needed", "Diagnostics did not find anything repairable.")
            return

        res = QMessageBox.warning(
            self,
            "Confirm repair",
            "A restore-point snapshot will be created before repairs run.\n\n"
            f"Repair actions queued: {total}\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            snapshot_path = create_versioned_backup(self._db, "repair")
        except Exception as e:
            log_exception(e, context="diagnostics.repair.snapshot", db_path=getattr(self._db, "path", None))
            QMessageBox.warning(self, "Snapshot failed", f"Could not create a pre-repair snapshot.\n\n{e}")
            return

        try:
            log_event(
                "Integrity repair started",
                context="diagnostics.repair",
                db_path=getattr(self._db, "path", None),
                details={"snapshot_path": str(snapshot_path), "queued_actions": int(total)},
            )
            result = self._db.repair_integrity_issues(report=report.get("integrity"))
        except Exception as e:
            log_exception(e, context="diagnostics.repair", db_path=getattr(self._db, "path", None))
            QMessageBox.critical(
                self,
                "Repair failed",
                f"Integrity repair failed.\n\nSnapshot kept at:\n{snapshot_path}\n\n{e}",
            )
            return
        log_event(
            "Integrity repair completed",
            context="diagnostics.repair",
            db_path=getattr(self._db, "path", None),
            details={
                "snapshot_path": str(snapshot_path),
                "remaining_issue_count": int(result.get("remaining_issue_count") or 0),
                "reset_broken_parent_links": int(result.get("reset_broken_parent_links") or 0),
                "normalized_sort_order_groups": int(result.get("normalized_sort_order_groups") or 0),
                "deleted_orphaned_custom_values": int(result.get("deleted_orphaned_custom_values") or 0),
            },
        )

        lines = [
            f"Pre-repair snapshot: {snapshot_path}",
            f"Broken parent links reset: {int(result.get('reset_broken_parent_links') or 0)}",
            f"Sibling groups normalized: {int(result.get('normalized_sort_order_groups') or 0)}",
            f"Sibling rows renumbered: {int(result.get('normalized_sort_order_rows') or 0)}",
            f"Orphaned custom values deleted: {int(result.get('deleted_orphaned_custom_values') or 0)}",
            f"Invalid recurrence rules deleted: {int(result.get('deleted_invalid_recurrence_rules') or 0)}",
            f"Invalid task recurrence refs cleared: {int(result.get('cleared_invalid_task_recurrence_refs') or 0)}",
            f"Invalid generated origins cleared: {int(result.get('cleared_invalid_generated_origins') or 0)}",
            f"Invalid task phase refs cleared: {int(result.get('cleared_invalid_task_phase_refs') or 0)}",
            f"Invalid PM dependencies deleted: {int(result.get('deleted_invalid_pm_dependencies') or 0)}",
            f"Remaining repairable issues: {int(result.get('remaining_issue_count') or 0)}",
        ]
        QMessageBox.information(self, "Repair completed", "\n".join(lines))
        self.refresh_report()

    def _open_path(self, path: str):
        if not path:
            return
        url = QUrl.fromLocalFile(path)
        QDesktopServices.openUrl(url)
