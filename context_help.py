from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget


CONTEXT_HELP_TOPICS: dict[str, str] = {
    "archive_browser": "archive",
    "capture_and_search": "quick-add",
    "custom_columns_dialog": "custom-columns",
    "dependency_picker_dialog": "projects",
    "details_panel": "details",
    "deliverable_dialog": "projects",
    "filter_panel": "search",
    "focus_panel": "focus-mode",
    "main_task_workspace": "task-tree",
    "milestone_dialog": "projects",
    "perspectives": "views",
    "project_cockpit": "projects",
    "register_entry_dialog": "projects",
    "relationships_panel": "relationships",
    "review_panel": "review",
    "snapshot_history": "backup",
    "template_variables_dialog": "templates",
    "workspace_manager": "workspaces",
    "calendar_agenda": "calendar",
    "analytics_panel": "analytics",
    "welcome_dialog": "onboarding",
    "project_tutorial": "project-tutorial",
}


def help_anchor_for_surface(surface_id: str) -> str | None:
    return CONTEXT_HELP_TOPICS.get(str(surface_id or "").strip())


def _resolve_help_opener(widget: QWidget | None) -> Callable[[str], None] | None:
    current = widget
    while current is not None:
        opener = getattr(current, "_open_help_anchor", None)
        if callable(opener):
            return opener
        current = current.parentWidget()
    return None


def open_context_help(widget: QWidget | None, surface_id: str) -> bool:
    anchor = help_anchor_for_surface(surface_id)
    if not anchor:
        return False
    opener = _resolve_help_opener(widget)
    if opener is None:
        return False
    opener(anchor)
    return True


def create_context_help_button(
    surface_id: str,
    host: QWidget,
    *,
    tooltip: str = "Open help for this view",
) -> QToolButton | None:
    anchor = help_anchor_for_surface(surface_id)
    if not anchor:
        return None
    btn = QToolButton(host)
    btn.setObjectName("ContextHelpButton")
    btn.setText("?")
    btn.setAutoRaise(False)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    btn.setToolTip(str(tooltip or "Open help for this view"))
    btn.setStatusTip(btn.toolTip())
    btn.setAccessibleName(f"Help for {surface_id.replace('_', ' ')}")
    btn.setProperty("context_help_surface", str(surface_id))
    btn.setProperty("context_help_anchor", anchor)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedSize(24, 24)
    btn.clicked.connect(lambda: open_context_help(host, surface_id))
    return btn


def attach_context_help(
    panel,
    surface_id: str,
    host: QWidget,
    *,
    tooltip: str = "Open help for this view",
):
    btn = create_context_help_button(surface_id, host, tooltip=tooltip)
    if btn is None:
        return None
    panel.header_actions.addWidget(btn)
    return btn


def create_context_help_header(
    title: str,
    surface_id: str,
    host: QWidget,
    *,
    tooltip: str = "Open help for this view",
) -> QWidget:
    row = QWidget(host)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QLabel(str(title or ""), row)
    label.setObjectName("ContextHeaderTitle")
    layout.addWidget(label)
    layout.addStretch(1)
    btn = create_context_help_button(surface_id, host, tooltip=tooltip)
    if btn is not None:
        layout.addWidget(btn)
    row._context_help_button = btn  # type: ignore[attr-defined]
    row._context_help_label = label  # type: ignore[attr-defined]
    return row
