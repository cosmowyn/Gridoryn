from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui_layout import add_left_aligned_buttons, configure_box_layout


class RelationshipsPanel(QWidget):
    focusTaskRequested = Signal(int)
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._lists: dict[str, QListWidget] = {}

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        intro_group = QGroupBox("Relationship inspector")
        intro_layout = QVBoxLayout(intro_group)
        configure_box_layout(intro_layout)
        self.intro = QLabel(
            "This panel surfaces direct relationships for the selected task: dependencies, tasks blocked by it, "
            "same-tag peers, same-project tasks, and project health context."
        )
        self.intro.setWordWrap(True)
        intro_layout.addWidget(self.intro)

        self.summary = QLabel("No task selected")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        intro_layout.addWidget(self.summary)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        intro_layout.addWidget(self.path_label)
        root.addWidget(intro_group)

        self._group_titles = {
            "children": "Children",
            "depends_on": "Depends on",
            "dependents": "Blocking",
            "same_tags": "Same tags",
            "same_project": "Same project",
            "same_waiting_for": "Same waiting context",
            "siblings": "Siblings",
        }

        for key in (
            "children",
            "depends_on",
            "dependents",
            "same_tags",
            "same_project",
            "same_waiting_for",
            "siblings",
        ):
            group = QGroupBox(self._group_titles[key])
            group.setObjectName(f"RelationshipsGroup_{key}")
            layout = QVBoxLayout(group)
            configure_box_layout(layout)
            lst = QListWidget()
            lst.setObjectName(f"RelationshipsList_{key}")
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lst.setToolTip(f"{self._group_titles[key]} for the selected task. Double-click to focus.")
            lst.setMinimumHeight(90)
            lst.setMaximumHeight(130)
            lst.itemDoubleClicked.connect(self._on_item_activated)
            layout.addWidget(lst)
            root.addWidget(group)
            self._lists[key] = lst

        actions = QHBoxLayout()
        self.focus_btn = QPushButton("Focus related task")
        self.focus_btn.setToolTip("Jump to the selected related task in the main tree.")
        self.close_btn = QPushButton("Hide inspector")
        self.close_btn.setToolTip("Hide the relationship inspector dock.")
        add_left_aligned_buttons(actions, self.focus_btn, self.close_btn)
        root.addLayout(actions)

        self.focus_btn.clicked.connect(self._emit_focus)
        self.close_btn.clicked.connect(self.closeRequested.emit)

    def _current_list(self) -> QListWidget | None:
        for lst in self._lists.values():
            if lst.hasFocus():
                return lst
        return next(iter(self._lists.values()), None)

    def _emit_focus(self):
        lst = self._current_list()
        if lst is None:
            return
        item = lst.currentItem()
        if item is None:
            return
        self._on_item_activated(item)

    def _on_item_activated(self, item: QListWidgetItem):
        if item is None:
            return
        try:
            task_id = int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            return
        if task_id > 0:
            self.focusTaskRequested.emit(task_id)

    def _format_task(self, row: dict) -> str:
        desc = str(row.get("description") or "")
        status = str(row.get("status") or "")
        prio = str(row.get("priority") or "")
        due = str(row.get("due_date") or "-")
        bits = [f"[P{prio}]", desc, status, f"due: {due}"]
        shared = row.get("shared_tags") or []
        if shared:
            bits.append("tags: " + ", ".join(str(tag) for tag in shared))
        waiting_age = row.get("waiting_age_days")
        if waiting_age is not None:
            bits.append(f"waiting {int(waiting_age)}d")
        return " | ".join(bit for bit in bits if str(bit).strip())

    def set_relationships(self, data: dict | None):
        if not data:
            self.summary.setText("No task selected")
            self.path_label.setText("")
            for key, lst in self._lists.items():
                lst.clear()
                parent = lst.parentWidget()
                if isinstance(parent, QGroupBox):
                    parent.setTitle(self._group_titles[key] + " (0)")
            return

        task = data.get("task") or {}
        project_summary = data.get("project_summary") or {}
        due_load = data.get("due_day_load") or {}

        summary_bits = [
            f"Selected: {str(task.get('description') or '')}",
            f"Status: {str(task.get('status') or '')}",
            f"Priority: {str(task.get('priority') or '')}",
        ]
        state_label = str(project_summary.get("state_label") or "").strip()
        if state_label:
            summary_bits.append(f"Project state: {state_label}")
        next_action = str(project_summary.get("next_action_description") or "").strip()
        if next_action:
            summary_bits.append(f"Next action: {next_action}")
        stalled_reason = str(project_summary.get("stalled_reason_text") or "").strip()
        if stalled_reason:
            summary_bits.append(f"Stalled because: {stalled_reason}")
        if str(due_load.get("warning") or "").strip():
            summary_bits.append(str(due_load.get("warning")))
        elif due_load:
            summary_bits.append(
                f"Due-day load: {int(due_load.get('task_count') or 0)} task(s), "
                f"{int(due_load.get('high_priority_count') or 0)} high-priority"
            )
        self.summary.setText(" | ".join(summary_bits))

        ancestors = data.get("ancestors") or []
        path_parts = [str(row.get("description") or "") for row in ancestors if str(row.get("description") or "").strip()]
        path_parts.append(str(task.get("description") or ""))
        self.path_label.setText("Project path: " + " > ".join(path_parts) if path_parts else "")

        for key, lst in self._lists.items():
            rows = data.get(key) or []
            lst.clear()
            for row in rows:
                item = QListWidgetItem(self._format_task(row))
                item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
                lst.addItem(item)
            if lst.count() > 0:
                lst.setCurrentRow(0)
            parent = lst.parentWidget()
            if isinstance(parent, QGroupBox):
                parent.setTitle(f"{self._group_titles[key]} ({len(rows)})")
