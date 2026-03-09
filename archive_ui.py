from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from context_help import attach_context_help
from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    EmptyStateStack,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_data_table,
    configure_box_layout,
    configure_form_layout,
    polish_button_layouts,
)


class ArchiveBrowserDialog(QDialog):
    def __init__(self, rows: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Archive Browser")
        self.setModal(True)
        self.resize(860, 420)

        self._rows = [dict(r) for r in (rows or [])]

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        intro_panel = SectionPanel(
            "Archive browser",
            "Browse archived task roots and restore only the items you want "
            "back in the active tree.",
        )
        self.help_btn = attach_context_help(
            intro_panel,
            "archive_browser",
            self,
            tooltip="Open help for archive browsing and restore",
        )
        root.addWidget(intro_panel)

        top = QFormLayout()
        configure_form_layout(top, label_width=80)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter archived tasks by description/status/date/priority")
        self.search.setToolTip("Filter archive list by keyword.")
        add_form_row(top, "Search", self.search)
        intro_panel.body_layout.addLayout(top)

        table_panel = SectionPanel(
            "Archived task roots",
            "The table below stays attached to its restore action instead of "
            "leaving buttons detached at the bottom of a blank dialog.",
        )
        root.addWidget(table_panel, 1)

        toolbar = QHBoxLayout()
        configure_box_layout(toolbar)
        self.archive_meta = QLabel("0 archived roots")
        toolbar.addWidget(self.archive_meta, 1)
        self.restore_btn = QPushButton("Restore selected")
        self.restore_btn.setToolTip("Restore selected archived task roots and their subtrees.")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Close archive browser without restoring.")
        add_left_aligned_buttons(
            toolbar,
            self.restore_btn,
            self.cancel_btn,
            trailing_stretch=False,
        )
        table_panel.body_layout.addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Task",
            "Archived at",
            "Status",
            "Priority",
            "Due",
            "Parent",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setToolTip("Archived tasks. Select one or more rows to restore.")
        configure_data_table(
            self.table,
            stretch_column=0,
            resize_to_contents=[1, 2, 3, 4],
            min_height=260,
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionsMovable(True)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table_stack = EmptyStateStack(
            self.table,
            "No archived task roots match the current filter.",
            "Adjust the filter or archive a task before restoring it.",
        )
        table_panel.body_layout.addWidget(self.table_stack, 1)

        self.search.textChanged.connect(self._rebuild)
        self.restore_btn.clicked.connect(self._accept_if_selection)
        self.cancel_btn.clicked.connect(self.reject)
        self.table.itemDoubleClicked.connect(lambda *_: self._accept_if_selection())

        polish_button_layouts(self)
        self._rebuild()

    def _matches(self, row: dict, q: str) -> bool:
        if not q:
            return True
        hay = " ".join(
            [
                str(row.get("description") or ""),
                str(row.get("status") or ""),
                str(row.get("archived_at") or ""),
                str(row.get("due_date") or ""),
                str(row.get("priority") or ""),
                str(row.get("parent_description") or ""),
            ]
        ).lower()
        return q in hay

    def _rebuild(self):
        q = self.search.text().strip().lower()
        view_rows = [r for r in self._rows if self._matches(r, q)]

        self.table.setRowCount(0)
        for r in view_rows:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)

            task = QTableWidgetItem(str(r.get("description") or ""))
            task.setData(Qt.ItemDataRole.UserRole, int(r.get("id") or 0))
            self.table.setItem(row_idx, 0, task)
            self.table.setItem(
                row_idx,
                1,
                QTableWidgetItem(str(r.get("archived_at") or "")),
            )
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(r.get("status") or "")))
            self.table.setItem(
                row_idx,
                3,
                QTableWidgetItem(str(r.get("priority") or "")),
            )
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(r.get("due_date") or "")))
            self.table.setItem(
                row_idx,
                5,
                QTableWidgetItem(str(r.get("parent_description") or "")),
            )

        self.table.resizeColumnsToContents()
        self.archive_meta.setText(f"{len(view_rows)} archived root item(s)")
        self.table_stack.set_has_content(bool(view_rows))
        self.restore_btn.setEnabled(bool(view_rows))

    def _accept_if_selection(self):
        if not self.selected_task_ids():
            return
        self.accept()

    def selected_task_ids(self) -> list[int]:
        ids = []
        seen = set()
        for idx in self.table.selectionModel().selectedRows(0):
            item = self.table.item(idx.row(), 0)
            if item is None:
                continue
            tid = item.data(Qt.ItemDataRole.UserRole)
            try:
                val = int(tid)
            except Exception:
                continue
            if val <= 0 or val in seen:
                continue
            seen.add(val)
            ids.append(val)
        return ids
