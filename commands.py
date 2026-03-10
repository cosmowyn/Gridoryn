from copy import deepcopy

from PySide6.QtGui import QUndoCommand


class AddTaskCommand(QUndoCommand):
    def __init__(self, model, parent_id, insert_row, task_template: dict):
        super().__init__("Add task")
        self.model = model
        self.parent_id = parent_id
        self.insert_row = insert_row
        self.task = dict(task_template)
        self.task_id = None

        # sibling order before add (for clean undo)
        self.before_siblings = model.sibling_order(parent_id)

    def redo(self):
        if self.task_id is None:
            self.task_id = self.model._db_insert_task(self.task)
        else:
            self.task["id"] = self.task_id
            self.model._db_restore_task(self.task)

        self.model._model_insert_task(self.task_id, self.parent_id, self.insert_row)

        # IMPORTANT: only renumber (no layoutChanged / no reorder signal)
        self.model._renumber_siblings(self.parent_id)

    def undo(self):
        self.model._model_remove_task(self.task_id)
        self.model.db.delete_task(self.task_id)

        # restore sibling ordering safely (DB update + full reload)
        self.model._apply_sibling_order(self.parent_id, self.before_siblings)


class DeleteSubtreeCommand(QUndoCommand):
    def __init__(self, model, task_id: int):
        super().__init__("Delete task")
        self.model = model
        self.root_id = int(task_id)

        root_node = model.node_for_id(self.root_id)
        self.parent_id = (
            root_node.parent.task["id"]
            if root_node and root_node.parent and root_node.parent.task
            else None
        )

        self.before_siblings = model.sibling_order(self.parent_id)

        # Snapshot subtree tasks in preorder (parent before children)
        self.subtree = model.snapshot_subtree(self.root_id)

    def redo(self):
        self.model._model_remove_task(self.root_id)
        self.model.db.delete_task(self.root_id)

        # IMPORTANT: only renumber (no layoutChanged / no reorder signal)
        self.model._renumber_siblings(self.parent_id)

    def undo(self):
        # restore subtree into DB
        self.model._db_restore_subtree(self.subtree)

        # restore sibling order safely (DB update + full reload)
        self.model._apply_sibling_order(self.parent_id, self.before_siblings)


class EditCellCommand(QUndoCommand):
    def __init__(self, model, task_id: int, col: int, old_value, new_value):
        super().__init__("Edit")
        self.model = model
        self.task_id = int(task_id)
        self.col = int(col)
        self.old = old_value
        self.new = new_value
        self.generated_task_id = None

    def redo(self):
        self.generated_task_id = self.model._apply_cell_change(self.task_id, self.col, self.new)

    def undo(self):
        self.model._apply_cell_change(self.task_id, self.col, self.old)
        if self.generated_task_id is not None and self.model.db.fetch_task_by_id(int(self.generated_task_id)):
            self.model.db.delete_task(int(self.generated_task_id))
            self.model.reload_all(reset_header_state=False)
        self.generated_task_id = None


class MoveNodeCommand(QUndoCommand):
    def __init__(self, model, task_id: int, new_parent_id, new_row: int):
        super().__init__("Move task")
        self.model = model
        self.task_id = int(task_id)

        node = model.node_for_id(self.task_id)
        self.old_parent_id = (
            node.parent.task["id"]
            if node and node.parent and node.parent.task
            else None
        )
        self.new_parent_id = new_parent_id
        self.new_row = int(new_row)

        self.old_parent_before = model.sibling_order(self.old_parent_id)
        self.new_parent_before = model.sibling_order(self.new_parent_id)

    def redo(self):
        self.model._model_move_node(self.task_id, self.new_parent_id, self.new_row)

    def undo(self):
        # Move back (this updates DB parent_id + sort_order for both parents)
        back_row = 0
        if self.task_id in self.old_parent_before:
            back_row = self.old_parent_before.index(self.task_id)

        self.model._model_move_node(self.task_id, self.old_parent_id, back_row)

        # Restore exact sibling orders safely (DB update + full reload)
        self.model._apply_sibling_orders_batch([
            (self.old_parent_id, self.old_parent_before),
            (self.new_parent_id, self.new_parent_before),
        ])


class AddCustomColumnCommand(QUndoCommand):
    def __init__(self, model, name: str, col_type: str, list_values: list[str] | None = None):
        super().__init__("Add custom column")
        self.model = model
        self.name = name
        self.col_type = col_type
        self.list_values = list(list_values or [])
        self.col_id = None

    def redo(self):
        if self.col_id is None:
            self.col_id = self.model.db.add_custom_column(self.name, self.col_type, self.list_values)
        else:
            self.model.db.restore_custom_column({
                "id": self.col_id,
                "name": self.name,
                "col_type": self.col_type,
                "created_at": self.model._now_iso(),
                "list_values": list(self.list_values),
            })
        self.model.reload_all(reset_header_state=True)

    def undo(self):
        self.model.db.remove_custom_column(self.col_id)
        self.model.reload_all(reset_header_state=True)


class RemoveCustomColumnCommand(QUndoCommand):
    def __init__(self, model, col_snapshot: dict, values_snapshot: dict):
        super().__init__("Remove custom column")
        self.model = model
        self.col = dict(col_snapshot)
        self.values = dict(values_snapshot)
        self.col_id = int(self.col["id"])

    def redo(self):
        self.model.db.remove_custom_column(self.col_id)
        self.model.reload_all(reset_header_state=True)

    def undo(self):
        self.model.db.restore_custom_column(self.col)
        for tid, v in self.values.items():
            self.model.db.update_custom_value(int(tid), self.col_id, v)
        self.model.reload_all(reset_header_state=True)


class TaskMutationCommand(QUndoCommand):
    def __init__(self, model, task_id: int, text: str, apply_fn, refresh_mode: str = "single"):
        super().__init__(text)
        self.model = model
        self.task_id = int(task_id)
        self.apply_fn = apply_fn
        self.refresh_mode = str(refresh_mode or "single")
        self.before = deepcopy(model.capture_task_snapshot(self.task_id))
        self.after = None

    def redo(self):
        if self.after is None:
            self.apply_fn()
            self.after = deepcopy(self.model.capture_task_snapshot(self.task_id))
            if self.after == self.before:
                self.setObsolete(True)
                return
        else:
            self.model._restore_task_snapshots([self.after], reload=(self.refresh_mode == "reload"))
            return
        self.model._refresh_after_task_mutation([self.task_id], reload=(self.refresh_mode == "reload"))

    def undo(self):
        if self.before is None:
            return
        self.model._restore_task_snapshots([self.before], reload=(self.refresh_mode == "reload"))


class TaskCollectionMutationCommand(QUndoCommand):
    def __init__(self, model, task_ids: list[int], text: str, apply_fn, refresh_mode: str = "reload"):
        super().__init__(text)
        self.model = model
        self.task_ids = [int(x) for x in task_ids if int(x) > 0]
        self.apply_fn = apply_fn
        self.refresh_mode = str(refresh_mode or "reload")
        self.before = [deepcopy(s) for s in model.capture_task_snapshots(self.task_ids)]
        self.after = None

    def redo(self):
        if self.after is None:
            self.apply_fn()
            self.after = [deepcopy(s) for s in self.model.capture_task_snapshots(self.task_ids)]
            if self.after == self.before:
                self.setObsolete(True)
                return
        else:
            self.model._restore_task_snapshots(self.after, reload=(self.refresh_mode == "reload"))
            return
        self.model._refresh_after_task_mutation(self.task_ids, reload=(self.refresh_mode == "reload"))

    def undo(self):
        if not self.before:
            return
        self.model._restore_task_snapshots(self.before, reload=(self.refresh_mode == "reload"))


class MilestoneMutationCommand(QUndoCommand):
    def __init__(self, model, milestone_id: int, text: str, apply_fn):
        super().__init__(text)
        self.model = model
        self.milestone_id = int(milestone_id)
        self.apply_fn = apply_fn
        self.before = deepcopy(model.capture_milestone_snapshot(self.milestone_id))
        self.after = None

    def redo(self):
        if self.after is None:
            self.apply_fn()
            self.after = deepcopy(self.model.capture_milestone_snapshot(self.milestone_id))
            if self.after == self.before:
                self.setObsolete(True)
                return
        else:
            self.model._restore_milestone_snapshot(self.after)
        self.model.reload_all(reset_header_state=False)

    def undo(self):
        if self.before is None:
            self.model.db.delete_milestone(int(self.milestone_id))
        else:
            self.model._restore_milestone_snapshot(self.before)
        self.model.reload_all(reset_header_state=False)


class DeliverableMutationCommand(QUndoCommand):
    def __init__(self, model, deliverable_id: int, text: str, apply_fn):
        super().__init__(text)
        self.model = model
        self.deliverable_id = int(deliverable_id)
        self.apply_fn = apply_fn
        self.before = deepcopy(model.capture_deliverable_snapshot(self.deliverable_id))
        self.after = None

    def redo(self):
        if self.after is None:
            self.apply_fn()
            self.after = deepcopy(self.model.capture_deliverable_snapshot(self.deliverable_id))
            if self.after == self.before:
                self.setObsolete(True)
                return
        else:
            self.model._restore_deliverable_snapshot(self.after)
        self.model.reload_all(reset_header_state=False)

    def undo(self):
        if self.before is None:
            self.model.db.delete_deliverable(int(self.deliverable_id))
        else:
            self.model._restore_deliverable_snapshot(self.before)
        self.model.reload_all(reset_header_state=False)


class ProjectPhaseMutationCommand(QUndoCommand):
    def __init__(self, model, phase_id: int, text: str, apply_fn):
        super().__init__(text)
        self.model = model
        self.phase_id = int(phase_id)
        self.apply_fn = apply_fn
        self.before = deepcopy(model.capture_project_phase_snapshot(self.phase_id))
        self.after = None

    def redo(self):
        if self.after is None:
            self.apply_fn()
            self.after = deepcopy(self.model.capture_project_phase_snapshot(self.phase_id))
            if self.after == self.before:
                self.setObsolete(True)
                return
        else:
            self.model._restore_project_phase_snapshot(self.after)
        self.model.reload_all(reset_header_state=False)

    def undo(self):
        if self.before is None:
            return
        self.model._restore_project_phase_snapshot(self.before)
        self.model.reload_all(reset_header_state=False)


class CreateTasksFromPayloadCommand(QUndoCommand):
    def __init__(self, model, payload: dict, parent_id: int | None = None, text: str = "Create tasks"):
        super().__init__(text)
        self.model = model
        self.payload = deepcopy(payload or {})
        self.parent_id = None if parent_id is None else int(parent_id)
        self.root_task_id: int | None = None
        self.created_payload = None

    def redo(self):
        if self.created_payload is None:
            self.root_task_id = self.model._create_tasks_from_template_payload_now(self.payload, parent_id=self.parent_id)
            if self.root_task_id is None:
                self.setObsolete(True)
                return
            self.created_payload = deepcopy(
                self.model._build_template_payload_from_task(int(self.root_task_id))
            )
        else:
            self.model._db_restore_template_payload(deepcopy(self.created_payload))
            tasks = self.created_payload.get("tasks") if isinstance(self.created_payload, dict) else None
            self.root_task_id = int(tasks[0]["id"]) if isinstance(tasks, list) and tasks else None

    def undo(self):
        if self.root_task_id is None:
            return
        self.model.db.delete_task(int(self.root_task_id))
        self.model.reload_all(reset_header_state=False)
