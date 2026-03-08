from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui_layout import (
    EmptyStateStack,
    SectionPanel,
    add_left_aligned_buttons,
    configure_box_layout,
)


class RelationshipsPanel(QWidget):
    focusTaskRequested = Signal(int)
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._lists: dict[str, QListWidget] = {}

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(8, 8, 8, 8), spacing=10)

        intro_panel = SectionPanel(
            "Relationship inspector",
            "Dependencies, structure, and shared context stay grouped by "
            "purpose instead of appearing as one long stack of unrelated lists.",
        )
        self.intro = QLabel(
            "This panel surfaces direct relationships for the selected "
            "task: dependencies, tasks blocked by it, same-tag peers, "
            "same-project tasks, and project health context."
        )
        self.intro.setWordWrap(True)
        intro_panel.body_layout.addWidget(self.intro)

        self.summary = QLabel("No task selected")
        self.summary.setObjectName("RelationshipsActiveTaskLabel")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        intro_panel.body_layout.addWidget(self.summary)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        intro_panel.body_layout.addWidget(self.path_label)
        root.addWidget(intro_panel)

        self._group_titles = {
            "children": "Children",
            "depends_on": "Depends on",
            "dependents": "Blocking",
            "same_tags": "Same tags",
            "same_project": "Same project",
            "same_waiting_for": "Same waiting context",
            "siblings": "Siblings",
        }

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        dependencies_tab = QWidget()
        dependencies_layout = QVBoxLayout(dependencies_tab)
        configure_box_layout(dependencies_layout)
        dependencies_split = QSplitter(Qt.Orientation.Horizontal)
        dependencies_split.setChildrenCollapsible(False)
        dependencies_layout.addWidget(dependencies_split, 1)
        dependencies_split.addWidget(
            self._build_list_section(
                "depends_on",
                "Depends on",
                "Direct predecessors that currently block this task.",
            )
        )
        dependencies_split.addWidget(
            self._build_list_section(
                "dependents",
                "Blocking",
                "Tasks that depend on the current task finishing first.",
            )
        )
        self.tabs.addTab(dependencies_tab, "Dependencies")

        structure_tab = QWidget()
        structure_layout = QVBoxLayout(structure_tab)
        configure_box_layout(structure_layout)
        structure_split = QSplitter(Qt.Orientation.Vertical)
        structure_split.setChildrenCollapsible(False)
        structure_layout.addWidget(structure_split, 1)
        structure_split.addWidget(
            self._build_list_section(
                "children",
                "Children",
                "Direct children of the current task or project.",
            )
        )
        mid_row = QWidget()
        mid_layout = QHBoxLayout(mid_row)
        configure_box_layout(mid_layout)
        mid_layout.addWidget(
            self._build_list_section(
                "siblings",
                "Siblings",
                "Tasks under the same parent or project level.",
            ),
            1,
        )
        mid_layout.addWidget(
            self._build_list_section(
                "same_project",
                "Same project",
                "Other tasks inside the same top-level project path.",
            ),
            1,
        )
        structure_split.addWidget(mid_row)
        self.tabs.addTab(structure_tab, "Structure")

        context_tab = QWidget()
        context_layout = QVBoxLayout(context_tab)
        configure_box_layout(context_layout)
        context_row = QHBoxLayout()
        configure_box_layout(context_row)
        context_row.addWidget(
            self._build_list_section(
                "same_tags",
                "Same tags",
                "Tasks sharing one or more tags with the current selection.",
            ),
            1,
        )
        context_row.addWidget(
            self._build_list_section(
                "same_waiting_for",
                "Same waiting context",
                "Tasks waiting on the same person, team, or external input.",
            ),
            1,
        )
        context_layout.addLayout(context_row, 1)
        self.tabs.addTab(context_tab, "Context")

        actions = QHBoxLayout()
        self.focus_btn = QPushButton("Focus related task")
        self.focus_btn.setToolTip("Jump to the selected related task in the main tree.")
        self.close_btn = QPushButton("Hide inspector")
        self.close_btn.setToolTip("Hide the relationship inspector dock.")
        add_left_aligned_buttons(actions, self.focus_btn, self.close_btn)
        root.addLayout(actions)

        self.focus_btn.clicked.connect(self._emit_focus)
        self.close_btn.clicked.connect(self.closeRequested.emit)

    def _build_list_section(
        self,
        key: str,
        title: str,
        subtitle: str,
    ) -> QWidget:
        panel = SectionPanel(title, subtitle)
        lst = QListWidget()
        lst.setObjectName(f"RelationshipsList_{key}")
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lst.setToolTip(
            f"{self._group_titles[key]} for the selected task. "
            "Double-click to focus."
        )
        lst.itemDoubleClicked.connect(self._on_item_activated)
        stack = EmptyStateStack(
            lst,
            f"No {title.lower()} right now.",
            "When related items exist, they will appear here.",
        )
        panel.body_layout.addWidget(stack, 1)
        panel.setObjectName(f"RelationshipsGroup_{key}")
        panel._stack = stack  # type: ignore[attr-defined]
        self._lists[key] = lst
        return panel

    def sizeHint(self) -> QSize:
        return QSize(520, 620)

    def minimumSizeHint(self) -> QSize:
        return QSize(360, 440)

    def _current_list(self) -> QListWidget | None:
        current_page = self.tabs.currentWidget()
        if isinstance(current_page, QWidget):
            page_lists = [
                lst for lst in self._lists.values()
                if current_page.isAncestorOf(lst)
            ]
            for lst in page_lists:
                if lst.hasFocus() or lst.selectedItems():
                    return lst
            if page_lists:
                return page_lists[0]
        for lst in self._lists.values():
            if lst.hasFocus() or lst.selectedItems():
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
            self.summary.setText("Active task: none")
            self.path_label.setText("")
            for key, lst in self._lists.items():
                lst.clear()
                stack = lst.parentWidget()
                if isinstance(stack, EmptyStateStack):
                    stack.set_has_content(False)
                panel = stack.parentWidget() if isinstance(stack, QWidget) else None
                if isinstance(panel, SectionPanel):
                    panel.title_label.setText(self._group_titles[key] + " (0)")
            return

        task = data.get("task") or {}
        project_summary = data.get("project_summary") or {}
        due_load = data.get("due_day_load") or {}

        summary_bits = [
            f"Active task: {str(task.get('description') or '')}",
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
        path_parts = [
            str(row.get("description") or "")
            for row in ancestors
            if str(row.get("description") or "").strip()
        ]
        path_parts.append(str(task.get("description") or ""))
        self.path_label.setText(
            "Project path: " + " > ".join(path_parts) if path_parts else ""
        )

        for key, lst in self._lists.items():
            rows = data.get(key) or []
            lst.clear()
            for row in rows:
                item = QListWidgetItem(self._format_task(row))
                item.setData(Qt.ItemDataRole.UserRole, int(row.get("id") or 0))
                lst.addItem(item)
            if lst.count() > 0:
                lst.setCurrentRow(0)
            stack = lst.parentWidget()
            if isinstance(stack, EmptyStateStack):
                stack.set_has_content(bool(rows))
            panel = stack.parentWidget() if isinstance(stack, QWidget) else None
            if isinstance(panel, SectionPanel):
                panel.title_label.setText(
                    f"{self._group_titles[key]} ({len(rows)})"
                )
