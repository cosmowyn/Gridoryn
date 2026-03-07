from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt

from db import Database
from model import TaskTreeModel


def _task_ids(model: TaskTreeModel) -> list[int]:
    return [int(node.task["id"]) for node in model.root.children if node.task]


def _description_column(model: TaskTreeModel) -> int:
    for idx in range(model.columnCount()):
        if model.column_key(idx) == "description":
            return idx
    raise AssertionError("description column missing")


def _source_index_for_task_id(model: TaskTreeModel, task_id: int, column: int = 0):
    node = model.node_for_id(int(task_id))
    if not node:
        return QModelIndex()
    return model._index_for_node(node, int(column))


def test_model_dragdrop_delete_and_undo_redo(tmp_path, qapp):
    db = Database(str(tmp_path / "tasks.sqlite3"))
    model = TaskTreeModel(db)

    assert model.add_task_with_values("Alpha")
    alpha_id = model.last_added_task_id()
    assert model.add_task_with_values("Bravo")
    bravo_id = model.last_added_task_id()
    assert model.add_task_with_values("Charlie")
    charlie_id = model.last_added_task_id()

    assert _task_ids(model) == [alpha_id, bravo_id, charlie_id]

    charlie_index = _source_index_for_task_id(model, charlie_id, 0)
    mime = model.mimeData([charlie_index])
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 0, 0, QModelIndex())
    assert _task_ids(model) == [charlie_id, alpha_id, bravo_id]

    model.undo_stack.undo()
    assert _task_ids(model) == [alpha_id, bravo_id, charlie_id]

    model.undo_stack.redo()
    assert _task_ids(model) == [charlie_id, alpha_id, bravo_id]

    model.delete_task(bravo_id)
    assert model.node_for_id(bravo_id) is None

    model.undo_stack.undo()
    assert model.node_for_id(bravo_id) is not None

    model.undo_stack.redo()
    assert model.node_for_id(bravo_id) is None


def test_model_custom_column_date_and_collapse_persistence(tmp_path, qapp):
    db = Database(str(tmp_path / "tasks.sqlite3"))
    model = TaskTreeModel(db)

    assert model.add_task_with_values("Dated task")
    task_id = model.last_added_task_id()

    model.add_custom_column("Follow-up", "date")
    cols = model.custom_columns_snapshot()
    follow_up = next(col for col in cols if str(col["name"]) == "Follow-up")

    follow_up_col = None
    for idx in range(model.columnCount()):
        if model.column_key(idx) == f"custom:{int(follow_up['id'])}":
            follow_up_col = idx
            break
    assert follow_up_col is not None

    source_index = _source_index_for_task_id(model, task_id, follow_up_col)
    assert source_index.isValid()
    assert model.setData(source_index, "2026-03-12", Qt.ItemDataRole.EditRole)
    assert db.fetch_task_by_id(task_id)["custom"][int(follow_up["id"])] == "2026-03-12"

    model.set_collapsed(task_id, True)
    assert int(db.fetch_task_by_id(task_id)["is_collapsed"] or 0) == 1

    model.set_collapsed(task_id, False)
    assert int(db.fetch_task_by_id(task_id)["is_collapsed"] or 0) == 0
