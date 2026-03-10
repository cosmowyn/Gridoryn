from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from PySide6.QtCore import (
    Qt, QAbstractItemModel, QModelIndex, QMimeData, QByteArray, QSettings
)
from PySide6.QtGui import QColor, QUndoStack, QIcon, QFont

from commands import (
    AddTaskCommand, DeleteSubtreeCommand, EditCellCommand, MoveNodeCommand,
    AddCustomColumnCommand, RemoveCustomColumnCommand,
    DeliverableMutationCommand, MilestoneMutationCommand, ProjectPhaseMutationCommand, TaskMutationCommand,
    TaskCollectionMutationCommand, CreateTasksFromPayloadCommand,
)
from category_folders_ui import folder_display_name, folder_icon
from project_intelligence import analyze_projects
from project_management import PROJECT_HEALTH_LABELS
from theme import ThemeManager


STATUSES = ["Todo", "In Progress", "Blocked", "Done"]
CUSTOM_TYPES = ["text", "int", "date", "bool", "list"]
PLANNED_BUCKETS = ["inbox", "today", "upcoming", "someday"]
RECURRENCE_FREQUENCIES = ["daily", "weekly", "monthly", "yearly"]


def _parse_iso_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_iso_datetime(s: str):
    raw = str(s or "").strip()
    if not raw:
        return None
    normalized = raw.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt)
        except Exception:
            continue
    for text, fmt in (
        (normalized[:19], "%Y-%m-%d %H:%M:%S"),
        (normalized[:16], "%Y-%m-%d %H:%M"),
        (normalized[:10], "%Y-%m-%d"),
    ):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _today():
    return date.today()


def _clamp(x: float, a: float, b: float) -> float:
    return a if x < a else b if x > b else x


def _lerp(a: int, b: int, t: float) -> int:
    t = _clamp(t, 0.0, 1.0)
    return int(round(a + (b - a) * t))


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(
        _lerp(c1.red(), c2.red(), t),
        _lerp(c1.green(), c2.green(), t),
        _lerp(c1.blue(), c2.blue(), t),
    )


def _tri_gradient(green: QColor, orange: QColor, red: QColor, t: float) -> QColor:
    t = _clamp(t, 0.0, 1.0)
    if t <= 0.5:
        return _lerp_color(green, orange, t / 0.5)
    return _lerp_color(orange, red, (t - 0.5) / 0.5)


def _best_contrast_text_color(bg: QColor) -> QColor:
    """Return black/white for best readability on a colored background."""
    r, g, b = bg.red(), bg.green(), bg.blue()
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return QColor("#000000") if luminance > 150 else QColor("#FFFFFF")


@dataclass
class _Node:
    task: Optional[dict]
    folder: Optional[dict]
    parent: Optional["_Node"]
    children: list["_Node"]

    def __init__(self, task=None, folder=None, parent=None):
        self.task = task
        self.folder = folder
        self.parent = parent
        self.children = []

    @property
    def is_task(self) -> bool:
        return self.task is not None

    @property
    def is_folder(self) -> bool:
        return self.folder is not None


class TaskTreeModel(QAbstractItemModel):
    MAX_NESTING_LEVELS = 10

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.undo_stack = QUndoStack(self)
        self.settings = QSettings()

        self.theme_mgr = ThemeManager(self.settings)
        self._last_applied_icon: QIcon | None = None

        self.core_cols = [
            ("description", "Task description", "text"),
            ("due_date", "Planned due date", "date"),
            ("reminder_at", "Reminder", "datetime"),
            ("last_update", "Last update", "datetime"),
            ("priority", "Priority", "int"),
            ("status", "Status", "status"),
            ("progress", "Progress", "progress"),
            ("project_health", "Health", "text"),
            ("next_action", "Next action", "text"),
            ("project_state", "State", "text"),
        ]

        self.custom_cols = []
        self.root = _Node(task=None, parent=None)
        self._id_map: dict[int, _Node] = {}
        self._folder_id_map: dict[int, _Node] = {}
        self._last_added_task_id: int | None = None
        self._project_health_cache: dict[int, dict] = {}
        self._project_management_health_cache: dict[int, dict] = {}

        self.reload_all(reset_header_state=False)

    # ---------- Theme ----------
    def apply_theme_to_app(self, app):
        self._last_applied_icon = self.theme_mgr.apply_to_app(app)

    def current_window_icon(self) -> QIcon | None:
        if self._last_applied_icon is not None and not self._last_applied_icon.isNull():
            return self._last_applied_icon
        theme = self.theme_mgr.load_theme(self.theme_mgr.current_theme_name())
        return self.theme_mgr.icon_for_theme(theme)

    # ---------- Load / rebuild ----------
    def reload_all(self, reset_header_state: bool = False):
        tasks = self.db.fetch_tasks()
        self.beginResetModel()
        self.custom_cols = self.db.fetch_custom_columns()
        self._rebuild_tree(tasks)
        self._rebuild_project_health_cache(tasks)
        self.endResetModel()

        if reset_header_state:
            self.settings.remove("ui/header_state")
            self.settings.remove("ui/header_state_keys")

    def _rebuild_project_health_cache(self, tasks: list[dict] | None = None):
        rows = tasks if tasks is not None else self.db.fetch_tasks()
        self._project_health_cache = {
            int(row["id"]): row
            for row in analyze_projects(rows, stalled_days=14, today=date.today())
        }
        self._project_management_health_cache = self.db.fetch_project_health_overview()
        return rows

    def _rebuild_tree(self, tasks: list[dict]):
        self.root = _Node(task=None, folder=None, parent=None)
        self._id_map = {}
        self._folder_id_map = {}

        folders = self.db.fetch_category_folders()
        for folder in folders:
            node = _Node(folder=dict(folder), parent=None)
            self._folder_id_map[int(folder["id"])] = node

        for folder in folders:
            folder_id = int(folder["id"])
            parent_folder_id = folder.get("parent_folder_id")
            node = self._folder_id_map[folder_id]
            if parent_folder_id is None:
                node.parent = self.root
                self.root.children.append(node)
                continue
            parent_node = self._folder_id_map.get(int(parent_folder_id))
            if parent_node is None:
                node.parent = self.root
                self.root.children.append(node)
            else:
                node.parent = parent_node
                parent_node.children.append(node)

        for task in tasks:
            node = _Node(task=task, parent=None)
            self._id_map[int(task["id"])] = node

        for task in tasks:
            task_id = int(task["id"])
            parent_id = task.get("parent_id")
            node = self._id_map[task_id]

            if parent_id is not None:
                parent_node = self._id_map.get(int(parent_id))
                if parent_node is not None:
                    node.parent = parent_node
                    parent_node.children.append(node)
                    continue

            folder_id = task.get("category_folder_id")
            folder_node = (
                self._folder_id_map.get(int(folder_id))
                if folder_id is not None
                else None
            )
            if folder_node is not None:
                node.parent = folder_node
                folder_node.children.append(node)
            else:
                node.parent = self.root
                self.root.children.append(node)

        def sort_children(node: _Node):
            def _sort_key(child: _Node):
                if child.folder:
                    return (
                        0,
                        int(child.folder.get("sort_order") or 0),
                        str(child.folder.get("name") or "").lower(),
                        int(child.folder.get("id") or 0),
                    )
                return (
                    1,
                    int(child.task.get("sort_order") or 0) if child.task else 0,
                    int(child.task.get("id") or 0) if child.task else 0,
                )

            node.children.sort(key=_sort_key)
            for child in node.children:
                sort_children(child)

        sort_children(self.root)

    # ---------- Helpers ----------
    def node_for_id(self, task_id: int) -> Optional[_Node]:
        return self._id_map.get(int(task_id))

    def folder_node_for_id(self, folder_id: int) -> Optional[_Node]:
        return self._folder_id_map.get(int(folder_id))

    def folder_id_from_index(self, index: QModelIndex) -> Optional[int]:
        if not index.isValid():
            return None
        node = index.internalPointer()
        if not node or not node.folder:
            return None
        return int(node.folder["id"])

    def max_nesting_levels(self) -> int:
        return self.MAX_NESTING_LEVELS

    def last_added_task_id(self) -> int | None:
        return self._last_added_task_id

    def _parent_node_for_id(self, parent_id: int | None) -> _Node:
        if parent_id is None:
            return self.root
        node = self.node_for_id(int(parent_id))
        return node if node is not None else self.root

    def _node_depth_from_top(self, node: _Node) -> int:
        """
        Depth relative to a top-level task:
        - top-level task => 0
        - its child => 1
        """
        depth = 0
        cur = node
        while cur.parent and cur.parent != self.root:
            depth += 1
            cur = cur.parent
        return depth

    def _subtree_max_relative_depth(self, node: _Node) -> int:
        if not node.children:
            return 0
        return 1 + max(self._subtree_max_relative_depth(ch) for ch in node.children)

    def _can_add_under_parent(self, parent_node: _Node) -> bool:
        if parent_node == self.root:
            return True
        return (self._node_depth_from_top(parent_node) + 1) <= self.MAX_NESTING_LEVELS

    def _can_place_subtree_under_parent(self, moving_node: _Node, new_parent_node: _Node) -> bool:
        moved_root_new_depth = 0 if new_parent_node == self.root else self._node_depth_from_top(new_parent_node) + 1
        deepest_after_move = moved_root_new_depth + self._subtree_max_relative_depth(moving_node)
        return deepest_after_move <= self.MAX_NESTING_LEVELS

    def can_add_child_task(self, parent_task_id: int) -> bool:
        parent_node = self.node_for_id(int(parent_task_id))
        if parent_node is None:
            return False
        return self._can_add_under_parent(parent_node)

    def task_id_from_index(self, index: QModelIndex) -> Optional[int]:
        if not index.isValid():
            return None
        node = index.internalPointer()
        if not node or not node.task:
            return None
        return int(node.task["id"])

    def category_folders(self) -> list[dict]:
        return self.db.fetch_category_folders()

    def column_key(self, logical_index: int) -> str:
        if logical_index < len(self.core_cols):
            return self.core_cols[logical_index][0]
        cc = self.custom_cols[logical_index - len(self.core_cols)]
        return f"custom:{cc['id']}"

    def custom_columns_snapshot(self):
        return list(self.custom_cols)

    def sibling_order(self, parent_id: int | None) -> list[int]:
        parent_node = self.root if parent_id is None else self.node_for_id(parent_id)
        if parent_node is None:
            parent_node = self.root
        return [int(ch.task["id"]) for ch in parent_node.children if ch.task]

    def _renumber_siblings(self, parent_id: int | None) -> None:
        """
        Reassign sequential sort_order values to the current in-memory sibling order
        and persist that order to the database.
        """
        parent_node = self.root if parent_id is None else self.node_for_id(parent_id)
        if parent_node is None:
            parent_node = self.root

        cur = self.db.conn.cursor()

        for i, ch in enumerate(parent_node.children, start=1):
            if not ch.task:
                continue
            task_id = int(ch.task["id"])
            ch.task["sort_order"] = i
            cur.execute(
                "UPDATE tasks SET sort_order=? WHERE id=?;",
                (i, task_id),
            )

        self.db.conn.commit()
        self._rebuild_project_health_cache()
        if parent_node.task:
            pidx0 = self._index_for_node(parent_node, 0)
            pidx_last = self._index_for_node(parent_node, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(pidx0, pidx_last, [Qt.ItemDataRole.DisplayRole])


    def _apply_sibling_order(self, parent_id: int | None, ordered_ids: list[int]) -> None:
        """
        Force the children of parent_id into the exact id order given by ordered_ids,
        then rewrite sort_order both in memory and in the database.

        This is used by undo/redo commands to restore a previous sibling order safely.
        """
        parent_node = self.root if parent_id is None else self.node_for_id(parent_id)
        if parent_node is None:
            parent_node = self.root

        # Current children mapped by id
        by_id = {}
        remaining = []
        for ch in parent_node.children:
            if ch.task:
                by_id[int(ch.task["id"])] = ch
            else:
                remaining.append(ch)

        # Rebuild children list in requested order
        new_children = []
        used = set()

        for tid in ordered_ids:
            node = by_id.get(int(tid))
            if node is not None:
                new_children.append(node)
                used.add(int(tid))

        # Append any children not present in ordered_ids at the end
        for ch in parent_node.children:
            if not ch.task:
                continue
            tid = int(ch.task["id"])
            if tid not in used:
                new_children.append(ch)

        # Preserve any taskless nodes too, just in case
        new_children.extend(remaining)

        self.beginResetModel()
        parent_node.children = new_children

        cur = self.db.conn.cursor()
        for i, ch in enumerate(parent_node.children, start=1):
            if not ch.task:
                continue
            task_id = int(ch.task["id"])
            ch.task["sort_order"] = i
            cur.execute(
                "UPDATE tasks SET sort_order=? WHERE id=?;",
                (i, task_id),
            )

        self.db.conn.commit()
        self._rebuild_project_health_cache()
        self.endResetModel()

        self.refresh_due_highlights()

    def snapshot_subtree(self, root_id: int) -> list[dict]:
        node = self.node_for_id(root_id)
        if not node:
            return []
        out = []

        def walk(n: _Node):
            tid = int(n.task["id"])
            snap = self.db.fetch_task_snapshot(tid)
            if snap is not None:
                out.append(snap)
            for c in n.children:
                walk(c)

        walk(node)
        return out

    def iter_nodes_preorder(self):
        def walk(n: _Node):
            for c in n.children:
                yield c
                yield from walk(c)
        yield from walk(self.root)

    # ---------- Stable index creation (for dataChanged) ----------
    def _row_in_parent(self, node: _Node) -> int:
        if not node.parent:
            return 0
        for i, ch in enumerate(node.parent.children):
            if ch is node:
                return i
        return 0

    def _index_for_node(self, node: _Node, column: int = 0) -> QModelIndex:
        if node is None or node == self.root or node.parent is None:
            return QModelIndex()
        parent = node.parent
        parent_index = QModelIndex() if parent == self.root else self._index_for_node(parent, 0)
        row = self._row_in_parent(node)
        return self.index(row, column, parent_index)

    # ---------- Model basics ----------
    def columnCount(self, parent=QModelIndex()):
        return len(self.core_cols) + len(self.custom_cols)

    def rowCount(self, parent=QModelIndex()):
        node = self.root if not parent.isValid() else parent.internalPointer()
        if not node:
            return 0
        return len(node.children)

    def index(self, row, column, parent=QModelIndex()):
        if column < 0 or column >= self.columnCount():
            return QModelIndex()

        parent_node = self.root if not parent.isValid() else parent.internalPointer()
        if not parent_node or row < 0 or row >= len(parent_node.children):
            return QModelIndex()

        child = parent_node.children[row]
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex):
        if not index.isValid():
            return QModelIndex()

        node = index.internalPointer()
        if not node or not node.parent or node.parent == self.root:
            return QModelIndex()

        parent_node = node.parent
        grand = parent_node.parent or self.root

        row = 0
        for i, ch in enumerate(grand.children):
            if ch is parent_node:
                row = i
                break

        return self.createIndex(row, 0, parent_node)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section < len(self.core_cols):
                return self.core_cols[section][1]
            return self.custom_cols[section - len(self.core_cols)]["name"]
        return str(section + 1)

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled

        node = index.internalPointer()
        if node and node.folder:
            return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

        base = (
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        if node and node.parent and node.parent.folder:
            base &= ~Qt.ItemFlag.ItemIsDragEnabled
            base &= ~Qt.ItemFlag.ItemIsDropEnabled
        key = self.column_key(index.column())
        if key not in {
            "last_update",
            "progress",
            "project_health",
            "next_action",
            "project_state",
        }:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    # ---------- Drag/drop ----------
    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self):
        return ["application/x-focus-todo-node"]

    def mimeData(self, indexes):
        ids = sorted({self.task_id_from_index(i) for i in indexes if i.isValid() and self.task_id_from_index(i) is not None})
        if not ids:
            return QMimeData()
        md = QMimeData()
        md.setData("application/x-focus-todo-node", QByteArray(str(ids[0]).encode("utf-8")))
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        if action != Qt.DropAction.MoveAction:
            return False
        if not data.hasFormat("application/x-focus-todo-node"):
            return False
        try:
            task_id = int(bytes(data.data("application/x-focus-todo-node")).decode("utf-8"))
        except Exception:
            return False

        dragged = self.node_for_id(task_id)
        if not dragged:
            return False

        new_parent_node = self.root if not parent.isValid() else parent.internalPointer()
        if not new_parent_node:
            new_parent_node = self.root
        if new_parent_node.folder:
            return False
        if dragged.parent and dragged.parent.folder:
            return False

        cur = new_parent_node
        while cur and cur.task:
            if int(cur.task["id"]) == task_id:
                return False
            cur = cur.parent

        old_parent_node = dragged.parent
        if old_parent_node is new_parent_node:
            return True

        if not self._can_place_subtree_under_parent(dragged, new_parent_node):
            return False

        return True

    def dropMimeData(self, data, action, row, column, parent):
        if not self.canDropMimeData(data, action, row, column, parent):
            return False

        task_id = int(bytes(data.data("application/x-focus-todo-node")).decode("utf-8"))
        new_parent_node = self.root if not parent.isValid() else parent.internalPointer()
        new_parent_id = None if new_parent_node == self.root else int(new_parent_node.task["id"])

        if row < 0:
            row = self.rowCount(parent)

        self.undo_stack.push(MoveNodeCommand(self, task_id, new_parent_id, row))
        return True

    # ---------- Data ----------
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        node = index.internalPointer()
        if not node:
            return None

        if node.folder:
            folder = node.folder
            display_name = folder_display_name(folder)

            if role == Qt.ItemDataRole.DisplayRole:
                return display_name if index.column() == 0 else ""
            if role == Qt.ItemDataRole.EditRole:
                return str(folder.get("name") or "") if index.column() == 0 else None
            if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
                return folder_icon(folder.get("icon_name"))
            if role == Qt.ItemDataRole.ToolTipRole:
                path = str(folder.get("path") or folder_name)
                color = str(folder.get("color_hex") or "").strip()
                icon_name = str(folder.get("icon_name") or "folder").strip()
                parts = [path]
                if color:
                    parts.append(f"Color: {color}")
                if icon_name:
                    parts.append(f"Icon: {icon_name}")
                return " | ".join(parts)
            if role == Qt.ItemDataRole.FontRole and index.column() == 0:
                font = QFont()
                font.setBold(True)
                return font
            if role == Qt.ItemDataRole.ForegroundRole and index.column() == 0:
                color = str(folder.get("color_hex") or "").strip()
                return QColor(color) if color else None
            if role == Qt.ItemDataRole.BackgroundRole:
                color = str(folder.get("color_hex") or "").strip()
                if color:
                    c = QColor(color)
                    c.setAlpha(26)
                    return c
                return QColor("#EEF2F7") if index.column() == 0 else None
            return None

        if not node.task:
            return None

        col = index.column()
        value = self._get_value(node.task, col, node)
        ctype = self._col_type(col)

        if role == Qt.ItemDataRole.DisplayRole:
            if ctype == "date":
                d = _parse_iso_date(value) if isinstance(value, str) else None
                return d.strftime("%d-%b-%Y") if d else ""
            if ctype == "datetime":
                dt = _parse_iso_datetime(value)
                return dt.strftime("%d-%b-%Y %H:%M") if dt else ("" if value is None else str(value))
            if ctype == "progress":
                return str(value or "")
            if ctype == "bool":
                return "Yes" if (value == "1" or value is True) else "No"
            return "" if value is None else str(value)

        if role == Qt.ItemDataRole.EditRole:
            return value

        if role == Qt.ItemDataRole.BackgroundRole:
            if self.column_key(col) == "project_health":
                return self._project_health_background(node.task)
            return self._due_background(node.task)

        # NEW: readable text on dynamic due-date rows (only when bg is set)
        if role == Qt.ItemDataRole.ForegroundRole:
            if self.column_key(col) == "project_health":
                bg = self._project_health_background(node.task)
                if isinstance(bg, QColor):
                    return _best_contrast_text_color(bg)
                return None
            bg = self._due_background(node.task)
            if isinstance(bg, QColor):
                return _best_contrast_text_color(bg)
            return None

        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if self.column_key(index.column()) in {
            "last_update",
            "progress",
            "project_health",
            "next_action",
            "project_state",
        }:
            return False

        node = index.internalPointer()
        task_id = int(node.task["id"])
        col = index.column()

        old = self._get_value(node.task, col, node)
        new = self._normalize_incoming(col, value)
        if self._col_type(col) == "list" and new is not None:
            self._ensure_list_option_for_column(col, str(new))
        if old == new:
            return False

        self.undo_stack.push(EditCellCommand(self, task_id, col, old, new))
        return True

    def _col_type(self, col: int) -> str:
        if col < len(self.core_cols):
            return self.core_cols[col][2]
        return self.custom_cols[col - len(self.core_cols)]["col_type"]

    def col_type_for_column(self, col: int) -> str:
        """Public helper for delegates/proxies: returns the logical column type."""
        return self._col_type(col)

    def _custom_col_meta(self, col: int) -> Optional[dict]:
        if col < len(self.core_cols):
            return None
        idx = col - len(self.core_cols)
        if idx < 0 or idx >= len(self.custom_cols):
            return None
        return self.custom_cols[idx]

    def list_options_for_column(self, col: int) -> list[str]:
        cc = self._custom_col_meta(col)
        if not cc or str(cc.get("col_type") or "") != "list":
            return []
        vals = cc.get("list_values") or []
        return [str(v) for v in vals]

    def _ensure_list_option_for_column(self, col: int, value: str):
        cc = self._custom_col_meta(col)
        if not cc or str(cc.get("col_type") or "") != "list":
            return
        val = str(value or "").strip()
        if not val:
            return
        current = cc.setdefault("list_values", [])
        if val in current:
            return
        if self.db.add_custom_column_list_value(int(cc["id"]), val):
            current.append(val)

    def _progress_text(self, node: _Node | None) -> str:
        if node is None or not node.task:
            return ""
        active_children = [c for c in node.children if c.task and not c.task.get("archived_at")]
        total = len(active_children)
        if total <= 0:
            return ""
        done = sum(1 for c in active_children if str(c.task.get("status") or "") == "Done")
        pct = int(round((100.0 * done) / total))
        return f"{done}/{total} ({pct}%)"

    def _project_summary(self, task_id: int | None) -> dict | None:
        if task_id is None:
            return None
        return self._project_health_cache.get(int(task_id))

    def _project_management_summary(self, task_id: int | None) -> dict | None:
        if task_id is None:
            return None
        return self._project_management_health_cache.get(int(task_id))

    def _project_state_text(self, task: dict, node: _Node | None) -> str:
        summary = self._project_summary(int(task.get("id") or 0))
        if summary:
            return str(summary.get("state_label") or "")
        if str(task.get("status") or "") == "Done":
            return ""
        if str(task.get("waiting_for") or "").strip():
            updated = _parse_iso_datetime(task.get("last_update"))
            if updated is not None:
                age = max(0, (date.today() - updated.date()).days)
                return f"Waiting {age}d" if age > 0 else "Waiting"
            return "Waiting"
        if int(task.get("blocked_by_count") or 0) > 0 or str(task.get("status") or "") == "Blocked":
            return "Blocked"
        if str(task.get("planned_bucket") or "").strip().lower() == "someday":
            return "Someday"
        if node is not None and node.children:
            return "Project"
        return "Ready"

    def _project_health_text(self, task: dict) -> str:
        summary = self._project_management_summary(int(task.get("id") or 0))
        if not summary:
            return ""
        health = str(summary.get("effective_health") or "").strip().lower()
        compact = {
            "awaiting_external_input": "Awaiting",
            "scope_drifting": "Scope drift",
        }
        return compact.get(
            health,
            str(summary.get("effective_health_label") or PROJECT_HEALTH_LABELS.get(health, "")),
        )

    def _project_health_background(self, task: dict) -> QColor | None:
        summary = self._project_management_summary(int(task.get("id") or 0))
        if not summary:
            return None
        health = str(summary.get("effective_health") or "").strip().lower()
        palette = {
            "on_track": QColor("#16A34A"),
            "at_risk": QColor("#F59E0B"),
            "delayed": QColor("#DC2626"),
            "blocked": QColor("#B91C1C"),
            "awaiting_external_input": QColor("#D97706"),
            "scope_drifting": QColor("#7C3AED"),
        }
        return palette.get(health)

    def _auto_mark_parent_done_chain(self, start_node: _Node | None) -> list[_Node]:
        changed_nodes: list[_Node] = []
        cur = start_node
        while cur and cur.task:
            active_children = [c for c in cur.children if c.task and not c.task.get("archived_at")]
            total = len(active_children)
            done = sum(1 for c in active_children if str(c.task.get("status") or "") == "Done")
            if total > 0 and done >= total and str(cur.task.get("status") or "") != "Done":
                tid = int(cur.task["id"])
                self.db.update_task_field(tid, "status", "Done")
                cur.task = self.db.fetch_task_by_id(tid)
                changed_nodes.append(cur)
            cur = cur.parent if (cur.parent and cur.parent.task) else None
        return changed_nodes

    def _get_value(self, task: dict, col: int, node: _Node | None = None):
        if col < len(self.core_cols):
            key = self.core_cols[col][0]
            if key == "progress":
                return self._progress_text(node)
            if key == "project_health":
                return self._project_health_text(task)
            if key == "next_action":
                summary = self._project_summary(int(task.get("id") or 0))
                return str(summary.get("next_action_badge") or "") if summary else ""
            if key == "project_state":
                return self._project_state_text(task, node)
            return task.get(key)
        cc = self.custom_cols[col - len(self.core_cols)]
        return task.get("custom", {}).get(cc["id"])

    def _normalize_incoming(self, col: int, value):
        t = self._col_type(col)

        if t == "date":
            if value is None:
                return None
            s = str(value).strip()
            if not s:
                return None
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return s[:10]
            return s

        if t == "datetime":
            if value is None:
                return None
            s = str(value).strip()
            if not s:
                return None
            dt = _parse_iso_datetime(s)
            if dt is not None:
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            return s

        if t == "int":
            try:
                return int(value)
            except Exception:
                return 3

        if t == "status":
            s = str(value)
            return s if s in STATUSES else "Todo"

        if t == "progress":
            return str(value or "")

        if t == "bool":
            if isinstance(value, bool):
                return "1" if value else "0"
            s = str(value).strip().lower()
            return "1" if s in {"1", "true", "yes", "y"} else "0"

        if t == "list":
            s = str(value or "").strip()
            return s if s else None

        return "" if value is None else str(value)

    # ---------- Smooth due-date gradient ----------
    def _due_background(self, task: dict):
        if task.get("status") == "Done":
            return None

        due = _parse_iso_date(task.get("due_date") or "")
        if not due:
            return None

        days = (due - _today()).days

        green = QColor("#00C853")
        orange = QColor("#FF9800")
        red = QColor("#D50000")

        far_days = 30
        due_days = 0
        overdue_soft = -7

        if days >= far_days:
            return green
        if days <= overdue_soft:
            return red

        t = (far_days - days) / float(far_days - due_days)
        return _tri_gradient(green, orange, red, t)

    def refresh_due_highlights(self):
        # safe minimal repaint trigger (top-level); avoids layoutChanged
        if self.rowCount() == 0 or self.columnCount() == 0:
            return
        tl = self.index(0, 0, QModelIndex())
        br = self.index(self.rowCount() - 1, self.columnCount() - 1, QModelIndex())
        if tl.isValid() and br.isValid():
            self.dataChanged.emit(
                tl,
                br,
                [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
            )

    # ---------- Public operations ----------
    def add_task_with_values(
        self,
        description: str,
        due_date: str | None = None,
        priority: int | None = None,
        parent_id: int | None = None,
        category_folder_id: int | None = None,
        planned_bucket: str | None = None,
        tags: list[str] | None = None,
        reminder_at: str | None = None,
    ) -> bool:
        parent_node = self._parent_node_for_id(parent_id)
        effective_parent_id = None if parent_node == self.root else int(parent_node.task["id"])

        if not self._can_add_under_parent(parent_node):
            return False

        bucket = str(planned_bucket or "inbox").strip().lower()
        if bucket not in PLANNED_BUCKETS:
            bucket = "inbox"

        task = {
            "description": str(description or ""),
            "due_date": due_date,
            "last_update": self._now_iso(),
            "priority": int(priority) if priority is not None else 3,
            "status": "Todo",
            "parent_id": effective_parent_id,
            "sort_order": self.db.next_sort_order(effective_parent_id),
            "is_collapsed": 0,
            "notes": "",
            "archived_at": None,
            "planned_bucket": bucket,
            "effort_minutes": None,
            "actual_minutes": 0,
            "timer_started_at": None,
            "waiting_for": None,
            "recurrence_rule_id": None,
            "recurrence_origin_task_id": None,
            "is_generated_occurrence": 0,
            "reminder_at": reminder_at,
            "reminder_minutes_before": None,
            "reminder_fired_at": None,
            "category_folder_id": (
                None if effective_parent_id is not None else category_folder_id
            ),
            "tags": list(tags or []),
            "custom": {},
        }

        insert_row = len(parent_node.children)
        cmd = AddTaskCommand(self, effective_parent_id, insert_row, task)
        self.undo_stack.push(cmd)
        self._last_added_task_id = int(cmd.task_id) if cmd.task_id is not None else None
        return True

    def add_task(self, parent_id: int | None = None) -> bool:
        return self.add_task_with_values("", None, None, parent_id=parent_id)

    def add_child_task(self, parent_task_id: int) -> bool:
        return self.add_task(parent_id=int(parent_task_id))

    def delete_task(self, task_id: int):
        self.undo_stack.push(DeleteSubtreeCommand(self, int(task_id)))

    def archive_task(self, task_id: int):
        self.archive_tasks([int(task_id)])

    def restore_task(self, task_id: int):
        self.restore_tasks([int(task_id)])

    def add_custom_column(self, name: str, col_type: str, list_values: list[str] | None = None):
        name = (name or "").strip()
        if not name:
            return
        if col_type not in CUSTOM_TYPES:
            col_type = "text"
        self.undo_stack.push(AddCustomColumnCommand(self, name, col_type, list_values))

    def remove_custom_column(self, col_id: int):
        col = None
        for c in self.custom_cols:
            if int(c["id"]) == int(col_id):
                col = dict(c)
                break
        if not col:
            return

        cur = self.db.conn.cursor()
        cur.execute("SELECT id, name, col_type, created_at FROM custom_columns WHERE id=?;", (int(col_id),))
        row = cur.fetchone()
        if not row:
            return
        col_full = dict(row)
        if str(col_full.get("col_type") or "") == "list":
            cur.execute(
                """
                SELECT value
                FROM custom_column_list_values
                WHERE column_id=?
                ORDER BY sort_order ASC, value ASC;
                """,
                (int(col_id),),
            )
            col_full["list_values"] = [str(r["value"]) for r in cur.fetchall()]

        values = {}
        for tid, node in self._id_map.items():
            v = node.task.get("custom", {}).get(int(col_id))
            if v is not None:
                values[tid] = v

        self.undo_stack.push(RemoveColumnCommandCompat(self, col_full, values))

    # ---------- High-level task helpers ----------
    def task_details(self, task_id: int) -> dict | None:
        return self.db.fetch_task_details(int(task_id))

    def task_relationships(self, task_id: int, limit: int = 12) -> dict:
        return self.db.fetch_task_relationships(int(task_id), limit=int(limit or 12))

    def all_tags(self) -> list[str]:
        return self.db.fetch_all_tags()

    def set_task_notes(self, task_id: int, notes: str):
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Edit notes",
                lambda: self.db.update_task_field(tid, "notes", str(notes or "")),
            )
        )

    def set_task_tags(self, task_id: int, tags):
        tid = int(task_id)
        normalized = list(tags or [])
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Edit tags",
                lambda: self.db.set_task_tags(tid, normalized),
            )
        )

    def set_task_bucket(self, task_id: int, bucket: str):
        b = str(bucket or "").strip().lower()
        if b not in PLANNED_BUCKETS:
            b = "inbox"
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Change bucket",
                lambda: self.db.update_task_field(tid, "planned_bucket", b),
            )
        )

    def set_task_start_date(self, task_id: int, start_date: str | None):
        value = str(start_date or "").strip() or None
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Change start date",
                lambda: self.db.update_task_field(tid, "start_date", value),
            )
        )

    def set_task_due_date(self, task_id: int, due_date: str | None):
        value = str(due_date or "").strip() or None
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Change due date",
                lambda: self.db.update_task_field(tid, "due_date", value),
            )
        )

    def set_task_waiting_for(self, task_id: int, waiting_for: str):
        text = str(waiting_for or "").strip()
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Edit waiting",
                lambda: self.db.update_task_field(tid, "waiting_for", text if text else None),
            )
        )

    def set_task_dependencies(self, task_id: int, depends_on_ids: list[int]):
        tid = int(task_id)
        deps = [int(x) for x in depends_on_ids or []]
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Edit dependencies",
                lambda: self.db.set_task_dependencies(tid, deps),
            )
        )

    def set_task_recurrence(self, task_id: int, frequency: str | None, create_next_on_done: bool):
        tid = int(task_id)
        freq = str(frequency or "").strip().lower() or None
        create_next = bool(create_next_on_done)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Edit recurrence",
                lambda: self.db.set_recurrence_for_task(tid, freq, create_next),
            )
        )

    def set_task_effort_minutes(self, task_id: int, minutes: int | None):
        val = None if minutes is None else max(0, int(minutes))
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Set estimate",
                lambda: self.db.update_task_field(tid, "effort_minutes", val),
            )
        )

    def set_task_actual_minutes(self, task_id: int, minutes: int):
        tid = int(task_id)
        value = max(0, int(minutes))
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Set time spent",
                lambda: self.db.update_task_field(tid, "actual_minutes", value),
            )
        )

    def start_task_timer(self, task_id: int):
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Start timer",
                lambda: self.db.start_timer(tid),
            )
        )

    def stop_task_timer(self, task_id: int):
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Stop timer",
                lambda: self.db.stop_timer(tid),
            )
        )

    def set_task_reminder(self, task_id: int, reminder_at_iso: str | None, minutes_before: int | None = None):
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Set reminder",
                lambda: self.db.set_task_reminder(tid, reminder_at_iso, minutes_before),
            )
        )

    def clear_task_reminder(self, task_id: int):
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Clear reminder",
                lambda: self.db.clear_task_reminder(tid),
            )
        )

    def fetch_pending_reminders(self, limit: int = 20) -> list[dict]:
        return self.db.fetch_pending_reminders(limit=int(limit))

    def mark_reminder_fired(self, task_id: int):
        tid = int(task_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Acknowledge reminder",
                lambda: self.db.mark_reminder_fired(tid),
            )
        )

    def is_task_archived(self, task_id: int) -> bool:
        node = self.node_for_id(int(task_id))
        if not node or not node.task:
            t = self.db.fetch_task_by_id(int(task_id))
            if not t:
                return False
            return bool(str(t.get("archived_at") or "").strip())
        return bool(str(node.task.get("archived_at") or "").strip())

    def fetch_archive_roots(self) -> list[dict]:
        return self.db.fetch_archive_roots()

    def fetch_review_data(
        self,
        waiting_days: int = 7,
        stalled_days: int = 14,
        recent_days: int = 30,
    ) -> dict[str, list[dict]]:
        return self.db.fetch_review_data(
            waiting_days=int(waiting_days),
            stalled_days=int(stalled_days),
            recent_days=int(recent_days),
        )

    def project_health_for_task(self, task_id: int, stalled_days: int = 14) -> dict | None:
        return self.db.project_health_for_task(int(task_id), stalled_days=int(stalled_days))

    def fetch_focus_data(self, include_waiting: bool = False, limit: int = 40) -> list[dict]:
        return self.db.fetch_focus_data(include_waiting=bool(include_waiting), limit=int(limit))

    def fetch_analytics_summary(self, trend_days: int = 14, tag_days: int = 30) -> dict:
        return self.db.fetch_analytics_summary(trend_days=int(trend_days), tag_days=int(tag_days))

    def project_id_for_task(self, task_id: int | None) -> int | None:
        if task_id is None:
            return None
        return self.db.project_id_for_task(int(task_id))

    def list_category_folders(self) -> list[dict]:
        return self.db.fetch_category_folders()

    def create_category_folder(
        self,
        name: str,
        parent_folder_id: int | None = None,
        *,
        color_hex: str | None = None,
        icon_name: str | None = None,
        identifier: str | None = None,
    ) -> int:
        folder_id = self.db.create_category_folder(
            name,
            parent_folder_id,
            color_hex=color_hex,
            icon_name=icon_name,
            identifier=identifier,
        )
        self.reload_all(reset_header_state=False)
        return folder_id

    def update_category_folder(self, folder_id: int, payload: dict):
        self.db.update_category_folder(int(folder_id), payload)
        self.reload_all(reset_header_state=False)

    def delete_category_folder(self, folder_id: int):
        self.db.delete_category_folder(int(folder_id))
        self.reload_all(reset_header_state=False)

    def assign_task_to_category_folder(self, task_id: int, folder_id: int | None):
        self.db.set_task_category_folder(int(task_id), folder_id)
        self.reload_all(reset_header_state=False)

    def list_project_candidates(self, folder_id: int | None = None) -> list[dict]:
        return self.db.list_project_candidates(folder_id=folder_id)

    def fetch_project_dashboard(self, project_task_id: int) -> dict | None:
        return self.db.fetch_project_dashboard(int(project_task_id))

    def ensure_project_profile(self, project_task_id: int) -> dict:
        data = self.db.ensure_project_profile(int(project_task_id))
        self.reload_all(reset_header_state=False)
        return data

    def save_project_profile(self, project_task_id: int, payload: dict) -> dict:
        data = self.db.save_project_profile(int(project_task_id), payload)
        self.reload_all(reset_header_state=False)
        return data

    def fetch_project_phases(self, project_task_id: int) -> list[dict]:
        return self.db.fetch_project_phases(int(project_task_id))

    def capture_project_phase_snapshot(self, phase_id: int) -> dict | None:
        return self.db.fetch_project_phase_by_id(int(phase_id))

    def _restore_project_phase_snapshot(self, snapshot: dict):
        self.db.restore_project_phase_snapshot(snapshot)

    def add_project_phase(self, project_task_id: int, name: str) -> int:
        phase_id = self.db.add_project_phase(int(project_task_id), name)
        self.reload_all(reset_header_state=False)
        return phase_id

    def update_project_phase(self, phase_id: int, name: str):
        self.db.update_project_phase(int(phase_id), name)
        self.reload_all(reset_header_state=False)

    def delete_project_phase(self, phase_id: int):
        self.db.delete_project_phase(int(phase_id))
        self.reload_all(reset_header_state=False)

    def set_task_phase(self, task_id: int, phase_id: int | None):
        normalized_phase_id = None if phase_id is None else int(phase_id)

        def apply():
            self.db.set_task_phase(int(task_id), normalized_phase_id)

        self.undo_stack.push(
            TaskMutationCommand(
                self,
                int(task_id),
                "Set task phase",
                apply,
                refresh_mode="single",
            )
        )

    def set_timeline_item_color(self, kind: str, item_id: int, color_hex: str | None):
        normalized_kind = str(kind or "").strip().lower()
        normalized_color = str(color_hex or "").strip() or None
        if normalized_kind in {"task", "project"}:
            task_id = int(item_id)

            def apply():
                self.db.set_task_gantt_color(task_id, normalized_color)

            self.undo_stack.push(
                TaskMutationCommand(
                    self,
                    task_id,
                    "Set Gantt item color" if normalized_color else "Reset Gantt item color",
                    apply,
                    refresh_mode="single",
                )
            )
            return

        if normalized_kind == "phase":
            phase_id = int(item_id)
            self.undo_stack.push(
                ProjectPhaseMutationCommand(
                    self,
                    phase_id,
                    "Set Gantt item color" if normalized_color else "Reset Gantt item color",
                    lambda: self.db.set_project_phase_gantt_color(phase_id, normalized_color),
                )
            )
            return

        if normalized_kind == "milestone":
            milestone_id = int(item_id)
            self.undo_stack.push(
                MilestoneMutationCommand(
                    self,
                    milestone_id,
                    "Set Gantt item color" if normalized_color else "Reset Gantt item color",
                    lambda: self.db.set_milestone_gantt_color(milestone_id, normalized_color),
                )
            )
            return

        if normalized_kind == "deliverable":
            deliverable_id = int(item_id)
            self.undo_stack.push(
                DeliverableMutationCommand(
                    self,
                    deliverable_id,
                    "Set Gantt item color" if normalized_color else "Reset Gantt item color",
                    lambda: self.db.set_deliverable_gantt_color(deliverable_id, normalized_color),
                )
            )

    def fetch_project_milestones(self, project_task_id: int) -> list[dict]:
        return self.db.fetch_project_milestones(int(project_task_id))

    def fetch_milestone_by_id(self, milestone_id: int) -> dict | None:
        return self.db.fetch_milestone_by_id(int(milestone_id))

    def capture_milestone_snapshot(self, milestone_id: int) -> dict | None:
        return self.db.fetch_milestone_by_id(int(milestone_id))

    def _restore_milestone_snapshot(self, snapshot: dict):
        self.db.restore_milestone_snapshot(snapshot)

    def upsert_milestone(self, payload: dict) -> int:
        milestone_id = self.db.upsert_milestone(payload)
        self.reload_all(reset_header_state=False)
        return int(milestone_id)

    def delete_milestone(self, milestone_id: int):
        self.db.delete_milestone(int(milestone_id))
        self.reload_all(reset_header_state=False)

    def set_milestone_dates(
        self,
        milestone_id: int,
        start_date: str | None,
        target_date: str | None,
    ):
        mid = int(milestone_id)
        current = self.db.fetch_milestone_by_id(mid)
        if not current:
            return
        payload = dict(current)
        payload["start_date"] = str(start_date or "").strip() or None
        payload["target_date"] = str(target_date or "").strip() or None
        self.undo_stack.push(
            MilestoneMutationCommand(
                self,
                mid,
                "Reschedule milestone",
                lambda: self.db.upsert_milestone(payload),
            )
        )

    def set_milestone_dependencies(self, milestone_id: int, dependency_refs: list[dict]):
        mid = int(milestone_id)
        current = self.db.fetch_milestone_by_id(mid)
        if not current:
            return
        payload = dict(current)
        payload["dependencies"] = list(dependency_refs or [])
        self.undo_stack.push(
            MilestoneMutationCommand(
                self,
                mid,
                "Edit milestone dependencies",
                lambda: self.db.upsert_milestone(payload),
            )
        )

    def fetch_project_deliverables(self, project_task_id: int) -> list[dict]:
        return self.db.fetch_project_deliverables(int(project_task_id))

    def fetch_deliverable_by_id(self, deliverable_id: int) -> dict | None:
        return self.db.fetch_deliverable_by_id(int(deliverable_id))

    def capture_deliverable_snapshot(self, deliverable_id: int) -> dict | None:
        return self.db.fetch_deliverable_by_id(int(deliverable_id))

    def _restore_deliverable_snapshot(self, snapshot: dict):
        self.db.restore_deliverable_snapshot(snapshot)

    def upsert_deliverable(self, payload: dict) -> int:
        deliverable_id = self.db.upsert_deliverable(payload)
        self.reload_all(reset_header_state=False)
        return int(deliverable_id)

    def delete_deliverable(self, deliverable_id: int):
        self.db.delete_deliverable(int(deliverable_id))
        self.reload_all(reset_header_state=False)

    def set_deliverable_due_date(self, deliverable_id: int, due_date: str | None):
        did = int(deliverable_id)
        current = self.db.fetch_deliverable_by_id(did)
        if not current:
            return
        payload = dict(current)
        payload["due_date"] = str(due_date or "").strip() or None
        self.undo_stack.push(
            DeliverableMutationCommand(
                self,
                did,
                "Reschedule deliverable",
                lambda: self.db.upsert_deliverable(payload),
            )
        )

    def fetch_project_register_entries(self, project_task_id: int, entry_type: str | None = None) -> list[dict]:
        return self.db.fetch_project_register_entries(int(project_task_id), entry_type=entry_type)

    def fetch_register_entry_by_id(self, entry_id: int) -> dict | None:
        return self.db.fetch_register_entry_by_id(int(entry_id))

    def upsert_project_register_entry(self, payload: dict) -> int:
        entry_id = self.db.upsert_project_register_entry(payload)
        self.reload_all(reset_header_state=False)
        return int(entry_id)

    def delete_project_register_entry(self, entry_id: int):
        self.db.delete_project_register_entry(int(entry_id))
        self.reload_all(reset_header_state=False)

    def fetch_project_baseline(self, project_task_id: int) -> dict | None:
        return self.db.fetch_project_baseline(int(project_task_id))

    def save_project_baseline(self, project_task_id: int, target_date: str | None, effort_minutes: int | None):
        self.db.save_project_baseline(int(project_task_id), target_date, effort_minutes)
        self.reload_all(reset_header_state=False)

    def add_attachment(self, task_id: int, path: str, label: str = ""):
        tid = int(task_id)
        p = str(path or "").strip()
        lbl = str(label or "")
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Add attachment",
                lambda: self.db.add_attachment(tid, p, lbl),
            )
        )

    def remove_attachment(self, attachment_id: int):
        att = self.db.fetch_attachment_by_id(int(attachment_id))
        if not att:
            return
        tid = int(att["task_id"])
        aid = int(attachment_id)
        self.undo_stack.push(
            TaskMutationCommand(
                self,
                tid,
                "Remove attachment",
                lambda: self.db.remove_attachment(aid),
                refresh_mode="reload",
            )
        )

    def list_saved_filter_views(self) -> list[dict]:
        return self.db.list_saved_filter_views()

    def save_filter_view(self, name: str, state: dict, overwrite: bool = True):
        self.db.save_filter_view(name, state, overwrite=bool(overwrite))

    def load_filter_view(self, name: str) -> dict | None:
        return self.db.load_filter_view(name)

    def delete_filter_view(self, name: str):
        self.db.delete_filter_view(name)

    def archive_tasks(self, task_ids: list[int]):
        roots = self._unique_task_ids(task_ids)
        if not roots:
            return
        affected = self._expand_task_ids_with_subtrees(roots)
        text = "Archive task" if len(roots) == 1 else "Archive tasks"
        self.undo_stack.push(
            TaskCollectionMutationCommand(
                self,
                affected,
                text,
                lambda: [self.db.archive_task(int(tid)) for tid in roots],
                refresh_mode="reload",
            )
        )

    def restore_tasks(self, task_ids: list[int]):
        roots = self._unique_task_ids(task_ids)
        if not roots:
            return
        affected = self._expand_task_ids_with_subtrees(roots)
        text = "Restore task" if len(roots) == 1 else "Restore tasks"
        self.undo_stack.push(
            TaskCollectionMutationCommand(
                self,
                affected,
                text,
                lambda: [self.db.restore_task(int(tid)) for tid in roots],
                refresh_mode="reload",
            )
        )

    def hard_delete_tasks(self, task_ids: list[int]):
        ids = sorted({int(x) for x in task_ids if int(x) > 0})
        # Delete deepest nodes first to avoid duplicate subtree deletion work
        ids.sort(key=lambda tid: self._node_depth_from_top(self.node_for_id(tid)) if self.node_for_id(tid) else 0, reverse=True)
        if not ids:
            return
        self.undo_stack.beginMacro("Delete permanently" if len(ids) == 1 else "Delete tasks permanently")
        try:
            for tid in ids:
                if self.node_for_id(tid):
                    self.delete_task(int(tid))
        finally:
            self.undo_stack.endMacro()

    def move_task_relative(self, task_id: int, delta: int) -> bool:
        node = self.node_for_id(int(task_id))
        if not node or not node.parent:
            return False
        parent_node = node.parent
        parent_id = None if parent_node == self.root else int(parent_node.task["id"])
        old_row = self._row_in_parent(node)
        new_row = max(0, min(old_row + int(delta), len(parent_node.children) - 1))
        if new_row == old_row:
            return False
        self.undo_stack.push(MoveNodeCommand(self, int(task_id), parent_id, new_row))
        return True

    def move_task_to_row(self, task_id: int, parent_id: int | None, row: int) -> bool:
        node = self.node_for_id(int(task_id))
        if not node or not node.parent:
            return False
        target_parent_id = None if parent_id is None else int(parent_id)
        self.undo_stack.push(
            MoveNodeCommand(self, int(task_id), target_parent_id, int(max(0, row)))
        )
        return True

    def duplicate_task(self, task_id: int, include_children: bool = False) -> int | None:
        node = self.node_for_id(int(task_id))
        if not node or not node.task:
            return None

        source_items = self.snapshot_subtree(int(task_id)) if include_children else [self.db.fetch_task_snapshot(int(task_id))]
        if not source_items:
            return None
        payload = {"tasks": []}
        for t in source_items:
            if not t:
                continue
            item = dict(t)
            item["custom"] = {str(k): v for k, v in (t.get("custom") or {}).items()}
            payload["tasks"].append(item)
        if not payload["tasks"]:
            return None
        text = "Duplicate task" if not include_children else "Duplicate task with children"
        cmd = CreateTasksFromPayloadCommand(self, payload, parent_id=payload["tasks"][0].get("parent_id"), text=text)
        self.undo_stack.push(cmd)
        return int(cmd.root_task_id) if cmd.root_task_id is not None else None

    def save_template_from_task(self, name: str, task_id: int):
        payload = self._build_template_payload_from_task(int(task_id))
        self.db.save_template(str(name or "").strip(), payload, overwrite=True)

    def list_templates(self) -> list[dict]:
        return self.db.list_templates()

    def delete_template(self, name: str):
        self.db.delete_template(name)

    def load_template_payload(self, name: str) -> dict | None:
        return self.db.load_template(name)

    def create_tasks_from_template_payload(self, payload: dict, parent_id: int | None = None) -> int | None:
        cmd = CreateTasksFromPayloadCommand(self, payload, parent_id=parent_id, text="Insert template")
        self.undo_stack.push(cmd)
        return int(cmd.root_task_id) if cmd.root_task_id is not None else None

    def create_tasks_from_template(self, name: str, parent_id: int | None = None) -> int | None:
        payload = self.db.load_template(name)
        return self.create_tasks_from_template_payload(payload, parent_id=parent_id)

    def _refresh_task_node_and_emit(self, task_id: int):
        node = self.node_for_id(int(task_id))
        if node and node.task:
            node.task = self.db.fetch_task_by_id(int(task_id))
            idx0 = self._index_for_node(node, 0)
            idx_last = self._index_for_node(node, self.columnCount() - 1)
            if idx0.isValid() and idx_last.isValid():
                self.dataChanged.emit(
                    idx0,
                    idx_last,
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
                )
            if node.parent and node.parent.task:
                pidx0 = self._index_for_node(node.parent, 0)
                pidx_last = self._index_for_node(node.parent, self.columnCount() - 1)
                if pidx0.isValid() and pidx_last.isValid():
                    self.dataChanged.emit(
                        pidx0,
                        pidx_last,
                        [Qt.ItemDataRole.DisplayRole],
                    )
        else:
            self.reload_all(reset_header_state=False)

    def _ancestor_task_ids(self, task_id: int) -> list[int]:
        node = self.node_for_id(int(task_id))
        if not node:
            return []
        out = []
        cur = node.parent
        while cur and cur.task:
            out.append(int(cur.task["id"]))
            cur = cur.parent
        return out

    def _now_iso(self) -> str:
        return datetime.now().replace(microsecond=0).isoformat(sep=" ")

    # ---------- DB helpers used by commands ----------
    def _db_insert_task(self, task: dict) -> int:
        return self.db.insert_task(task, keep_id=False)

    def _db_restore_task(self, task: dict):
        self.db.insert_task(task, keep_id=True)

    def _db_restore_subtree(self, subtree: list[dict]):
        for t in subtree:
            self.db.insert_task(t, keep_id=True)
        for t in subtree:
            self.db.restore_task_snapshot(t)
        self.reload_all(reset_header_state=False)

    def _db_restore_template_payload(self, payload: dict):
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list) or not tasks:
            return
        task_id_map: dict[int, int] = {}
        for t in tasks:
            old_id = t.get("id")
            if old_id is None:
                continue
            self.db.insert_task(t, keep_id=True)
            task_id_map[int(old_id)] = int(old_id)
        for t in tasks:
            self.db.restore_task_snapshot(t)
        self.db.restore_project_template_payload(payload, task_id_map)
        self.reload_all(reset_header_state=False)

    def capture_task_snapshot(self, task_id: int) -> dict | None:
        return self.db.fetch_task_snapshot(int(task_id))

    def capture_task_snapshots(self, task_ids: list[int]) -> list[dict]:
        out = []
        seen = set()
        for tid in task_ids or []:
            try:
                task_id = int(tid)
            except Exception:
                continue
            if task_id <= 0 or task_id in seen:
                continue
            seen.add(task_id)
            snap = self.capture_task_snapshot(task_id)
            if snap is not None:
                out.append(snap)
        return out

    def _restore_task_snapshots(self, snapshots: list[dict], reload: bool = False):
        if not snapshots:
            return
        for snap in snapshots:
            self.db.restore_task_snapshot(snap)
        task_ids = [int(s["id"]) for s in snapshots if s and s.get("id") is not None]
        self._refresh_after_task_mutation(task_ids, reload=bool(reload))

    def _refresh_after_task_mutation(self, task_ids: list[int], reload: bool = False):
        ids = self._unique_task_ids(task_ids)
        if reload:
            self.reload_all(reset_header_state=False)
            return
        self._rebuild_project_health_cache()
        refresh_ids: list[int] = []
        seen: set[int] = set()
        for tid in ids:
            for candidate in [int(tid), *self._ancestor_task_ids(int(tid))]:
                if candidate in seen:
                    continue
                seen.add(candidate)
                refresh_ids.append(candidate)
        for refresh_id in refresh_ids:
            self._refresh_task_node_and_emit(int(refresh_id))

    def _unique_task_ids(self, task_ids: list[int]) -> list[int]:
        ids = []
        seen = set()
        for raw in task_ids or []:
            try:
                tid = int(raw)
            except Exception:
                continue
            if tid <= 0 or tid in seen:
                continue
            seen.add(tid)
            ids.append(tid)
        return ids

    def _expand_task_ids_with_subtrees(self, task_ids: list[int]) -> list[int]:
        out = []
        seen = set()
        for tid in self._unique_task_ids(task_ids):
            for child_id in self.db.fetch_subtree_task_ids(int(tid)):
                if child_id in seen:
                    continue
                seen.add(child_id)
                out.append(int(child_id))
        return out

    def _build_template_payload_from_task(self, task_id: int) -> dict:
        root_id = int(task_id)
        subtree = self.snapshot_subtree(root_id)
        payload = {"tasks": []}
        subtree_ids = {int(t["id"]) for t in subtree if t and t.get("id") is not None}
        include_project_template = self.db.fetch_project_profile(root_id) is not None
        project_template = (
            self.db.build_project_template_payload(root_id, task_ids=subtree_ids)
            if include_project_template
            else None
        )

        for t in subtree:
            tid = int(t["id"])
            item = dict(t)
            item["custom"] = {str(k): v for k, v in (t.get("custom") or {}).items()}
            item["attachments"] = self.db.fetch_attachments(tid)
            item["dependencies"] = [int(d["id"]) for d in self.db.fetch_dependencies(tid)]
            item["phase_id"] = None
            payload["tasks"].append(item)
        if isinstance(project_template, dict):
            payload["project_template"] = project_template
        return payload

    def _create_tasks_from_template_payload_now(self, payload: dict, parent_id: int | None = None) -> int | None:
        if not payload:
            return None
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list) or not tasks:
            return None

        root_old_id = int(tasks[0]["id"])
        old_to_new: dict[int, int] = {}
        first_new: int | None = None

        for t in tasks:
            old_id = int(t["id"])
            new_task = dict(t)
            new_task.pop("id", None)
            new_task["custom"] = {int(k): v for k, v in (t.get("custom") or {}).items()}
            new_task.pop("created_at", None)
            new_task["last_update"] = self._now_iso()
            new_task["is_collapsed"] = 0
            new_task["phase_id"] = None
            new_task["recurrence_rule_id"] = None
            new_task["recurrence_origin_task_id"] = None
            new_task["is_generated_occurrence"] = 0
            new_task["reminder_at"] = None
            new_task["reminder_minutes_before"] = None
            new_task["reminder_fired_at"] = None

            if old_id == root_old_id:
                new_parent = parent_id
            else:
                src_parent = t.get("parent_id")
                if src_parent is None:
                    new_parent = parent_id
                else:
                    new_parent = old_to_new.get(int(src_parent), parent_id)
            new_task["parent_id"] = new_parent
            new_task["sort_order"] = self.db.next_sort_order(new_parent)

            new_id = int(self.db.insert_task(new_task, keep_id=False))
            old_to_new[old_id] = new_id
            if first_new is None:
                first_new = new_id

            for att in t.get("attachments") or []:
                try:
                    self.db.add_attachment(
                        new_id,
                        str(att.get("path") or ""),
                        str(att.get("label") or ""),
                    )
                except Exception:
                    continue

        for t in tasks:
            old_id = int(t["id"])
            new_id = old_to_new.get(old_id)
            if not new_id:
                continue
            deps = [old_to_new.get(int(d)) for d in (t.get("dependencies") or [])]
            mapped = [int(x) for x in deps if x]
            if mapped:
                self.db.set_task_dependencies(new_id, mapped)

        self.db.restore_project_template_payload(payload, old_to_new)

        self.reload_all(reset_header_state=False)
        return first_new

    # ---------- Collapse persistence helpers ----------
    def set_collapsed(self, task_id: int, collapsed: bool):
        self.db.set_task_collapsed(task_id, collapsed)
        node = self.node_for_id(task_id)
        if node and node.task:
            node.task["is_collapsed"] = 1 if collapsed else 0

    # ---------- Internal model helpers used by commands ----------
    def _task_container_node(self, task: dict | None) -> _Node:
        if task is None:
            return self.root
        folder_id = task.get("category_folder_id")
        if folder_id is None:
            return self.root
        folder_node = self.folder_node_for_id(int(folder_id))
        return folder_node if folder_node is not None else self.root

    def _model_insert_task(self, task_id: int, parent_id: int | None, row: int):
        t = self.db.fetch_task_by_id(task_id)
        parent_node = self._task_container_node(t) if parent_id is None else self.node_for_id(parent_id)
        if not parent_node:
            parent_node = self.root

        parent_index = QModelIndex() if parent_node == self.root else self._index_for_node(parent_node, 0)
        row = max(0, min(row, len(parent_node.children)))

        self.beginInsertRows(parent_index, row, row)

        node = _Node(task=t, parent=parent_node)
        self._id_map[int(task_id)] = node
        parent_node.children.insert(row, node)

        self.endInsertRows()
        self._rebuild_project_health_cache()
        if parent_node.task:
            pidx0 = self._index_for_node(parent_node, 0)
            pidx_last = self._index_for_node(parent_node, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(pidx0, pidx_last, [Qt.ItemDataRole.DisplayRole])
        self.refresh_due_highlights()

    def _model_remove_task(self, task_id: int):
        node = self.node_for_id(task_id)
        if not node or not node.parent:
            return

        parent_node = node.parent
        parent_index = QModelIndex() if parent_node == self.root else self._index_for_node(parent_node, 0)

        row = self._row_in_parent(node)

        self.beginRemoveRows(parent_index, row, row)

        parent_node.children.pop(row)

        def drop_ids(n: _Node):
            if n.task:
                self._id_map.pop(int(n.task["id"]), None)
            for c in n.children:
                drop_ids(c)

        drop_ids(node)

        self.endRemoveRows()
        self._rebuild_project_health_cache()

        changed_parents: list[_Node] = []
        if parent_node.task:
            changed_parents = self._auto_mark_parent_done_chain(parent_node)

        if parent_node.task:
            pidx0 = self._index_for_node(parent_node, 0)
            pidx_last = self._index_for_node(parent_node, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(pidx0, pidx_last, [Qt.ItemDataRole.DisplayRole])

        for pnode in changed_parents:
            pidx0 = self._index_for_node(pnode, 0)
            pidx_last = self._index_for_node(pnode, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(
                    pidx0,
                    pidx_last,
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
                )
            if pnode.parent and pnode.parent.task:
                gpidx0 = self._index_for_node(pnode.parent, 0)
                gpidx_last = self._index_for_node(pnode.parent, self.columnCount() - 1)
                if gpidx0.isValid() and gpidx_last.isValid():
                    self.dataChanged.emit(gpidx0, gpidx_last, [Qt.ItemDataRole.DisplayRole])

        self.refresh_due_highlights()

    def _apply_sibling_orders_batch(self, orders: list[tuple[int | None, list[int]]]) -> None:
        seen: set[str] = set()
        for parent_id, ordered_ids in orders or []:
            key = "root" if parent_id is None else str(int(parent_id))
            if key in seen:
                continue
            seen.add(key)
            self._apply_sibling_order(parent_id, list(ordered_ids or []))

    def _apply_cell_change(self, task_id: int, col: int, new_value):
        """
        IMPORTANT: never emit layoutChanged here.
        Emit dataChanged for the row only.
        """
        node = self.node_for_id(task_id)
        if not node or not node.task:
            return

        old_status = str(node.task.get("status") or "")
        edited_key = None

        if col < len(self.core_cols):
            key = self.core_cols[col][0]
            edited_key = key
            if key in {"description", "due_date", "priority", "status", "reminder_at"}:
                if key == "reminder_at":
                    self.db.update_task_fields(
                        int(task_id),
                        {
                            "reminder_at": new_value,
                            "reminder_fired_at": None,
                        },
                    )
                else:
                    self.db.update_task_field(task_id, key, new_value)
        else:
            cc = self.custom_cols[col - len(self.core_cols)]
            self.db.update_custom_value(task_id, cc["id"], new_value)

        generated_task_id = None
        if edited_key == "status":
            new_status = str(new_value or "")
            if old_status != "Done" and new_status == "Done":
                generated_task_id = self.db.maybe_create_next_recurrence(int(task_id))

        if generated_task_id is not None:
            self.reload_all(reset_header_state=False)
            return int(generated_task_id)

        node.task = self.db.fetch_task_by_id(task_id)
        auto_completed_parents: list[_Node] = []
        if edited_key == "status":
            auto_completed_parents = self._auto_mark_parent_done_chain(node.parent)
        self._rebuild_project_health_cache()

        idx0 = self._index_for_node(node, 0)
        idx_last = self._index_for_node(node, self.columnCount() - 1)
        if idx0.isValid() and idx_last.isValid():
            self.dataChanged.emit(
                idx0,
                idx_last,
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
            )

        # Parent row may expose progress rollup that depends on child changes.
        if node.parent and node.parent.task:
            pidx0 = self._index_for_node(node.parent, 0)
            pidx_last = self._index_for_node(node.parent, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(pidx0, pidx_last, [Qt.ItemDataRole.DisplayRole])

        for pnode in auto_completed_parents:
            pidx0 = self._index_for_node(pnode, 0)
            pidx_last = self._index_for_node(pnode, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(
                    pidx0,
                    pidx_last,
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
                )
            if pnode.parent and pnode.parent.task:
                gpidx0 = self._index_for_node(pnode.parent, 0)
                gpidx_last = self._index_for_node(pnode.parent, self.columnCount() - 1)
                if gpidx0.isValid() and gpidx_last.isValid():
                    self.dataChanged.emit(gpidx0, gpidx_last, [Qt.ItemDataRole.DisplayRole])
        return None

    def _model_move_node(self, task_id: int, new_parent_id: int | None, new_row: int):
        node = self.node_for_id(task_id)
        if not node or not node.parent:
            return

        old_parent_node = node.parent
        old_parent_id = None if old_parent_node == self.root else int(old_parent_node.task["id"])

        new_parent_node = self.root if new_parent_id is None else self.node_for_id(new_parent_id)
        if not new_parent_node:
            new_parent_node = self.root

        # prevent cycles
        cur = new_parent_node
        while cur and cur.task:
            if int(cur.task["id"]) == task_id:
                return
            cur = cur.parent

        if old_parent_node is not new_parent_node:
            if not self._can_place_subtree_under_parent(node, new_parent_node):
                return

        old_parent_index = QModelIndex() if old_parent_node == self.root else self._index_for_node(old_parent_node, 0)
        new_parent_index = QModelIndex() if new_parent_node == self.root else self._index_for_node(new_parent_node, 0)

        from_row = self._row_in_parent(node)

        new_row = max(0, min(new_row, len(new_parent_node.children)))
        dest_row = new_row
        if old_parent_node is new_parent_node and new_row > from_row:
            dest_row += 1

        self.beginMoveRows(old_parent_index, from_row, from_row, new_parent_index, dest_row)

        old_parent_node.children.pop(from_row)
        node.parent = new_parent_node
        new_parent_node.children.insert(new_row, node)

        self.endMoveRows()

        old_order = [int(ch.task["id"]) for ch in old_parent_node.children if ch.task]
        new_order = [int(ch.task["id"]) for ch in new_parent_node.children if ch.task]

        self.db.move_task(
            task_id=task_id,
            new_parent_id=new_parent_id,
            old_parent_id=old_parent_id,
            old_parent_order=old_order,
            new_parent_order=new_order,
        )

        old_sort_order = 1
        for ch in old_parent_node.children:
            if not ch.task:
                continue
            ch.task["sort_order"] = old_sort_order
            old_sort_order += 1

        new_sort_order = 1
        for ch in new_parent_node.children:
            if not ch.task:
                continue
            ch.task["sort_order"] = new_sort_order
            new_sort_order += 1
            if int(ch.task["id"]) == task_id:
                ch.task["parent_id"] = new_parent_id

        changed_parents: list[_Node] = []
        if old_parent_node.task:
            changed_parents.extend(self._auto_mark_parent_done_chain(old_parent_node))
        if new_parent_node.task and new_parent_node is not old_parent_node:
            changed_parents.extend(self._auto_mark_parent_done_chain(new_parent_node))
        self._rebuild_project_health_cache()

        for parent_node in (old_parent_node, new_parent_node):
            if parent_node.task:
                pidx0 = self._index_for_node(parent_node, 0)
                pidx_last = self._index_for_node(parent_node, self.columnCount() - 1)
                if pidx0.isValid() and pidx_last.isValid():
                    self.dataChanged.emit(pidx0, pidx_last, [Qt.ItemDataRole.DisplayRole])

        for pnode in changed_parents:
            pidx0 = self._index_for_node(pnode, 0)
            pidx_last = self._index_for_node(pnode, self.columnCount() - 1)
            if pidx0.isValid() and pidx_last.isValid():
                self.dataChanged.emit(
                    pidx0,
                    pidx_last,
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
                )

        self.refresh_due_highlights()


class RemoveColumnCommandCompat(RemoveCustomColumnCommand):
    pass
