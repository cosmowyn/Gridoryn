from __future__ import annotations

from datetime import date, timedelta

from db import Database, LATEST_SCHEMA_VERSION, now_iso


def test_database_core_crud_archive_and_recurrence(tmp_path):
    db = Database(str(tmp_path / "tasks.sqlite3"))

    assert db.schema_user_version() == LATEST_SCHEMA_VERSION

    stage_col = db.add_custom_column("Stage", "list", ["Idea", "Doing", "Done"])

    parent_id = db.insert_task(
        {
            "description": "Parent project",
            "due_date": date.today().isoformat(),
            "priority": 2,
            "status": "In Progress",
            "sort_order": 1,
            "last_update": now_iso(),
            "tags": ["work"],
        }
    )
    child_id = db.insert_task(
        {
            "description": "Child task",
            "parent_id": parent_id,
            "sort_order": 1,
            "last_update": now_iso(),
            "custom": {stage_col: "Doing"},
        }
    )

    child = db.fetch_task_by_id(child_id)
    assert child["parent_id"] == parent_id
    assert child["custom"][stage_col] == "Doing"

    db.update_custom_value(child_id, stage_col, "Done")
    assert db.fetch_task_by_id(child_id)["custom"][stage_col] == "Done"

    db.archive_task(parent_id)
    assert db.fetch_task_by_id(parent_id)["archived_at"]
    assert db.fetch_task_by_id(child_id)["archived_at"]

    db.restore_task(parent_id)
    assert db.fetch_task_by_id(parent_id)["archived_at"] is None
    assert db.fetch_task_by_id(child_id)["archived_at"] is None

    db.set_recurrence_for_task(parent_id, "weekly", create_next_on_done=True)
    parent = db.fetch_task_by_id(parent_id)
    assert parent["recurrence"]["frequency"] == "weekly"

    db.update_task_field(parent_id, "status", "Done")
    next_id = db.maybe_create_next_recurrence(parent_id)
    assert isinstance(next_id, int) and next_id > 0
    next_task = db.fetch_task_by_id(next_id)
    assert next_task["status"] == "Todo"
    assert next_task["recurrence_origin_task_id"] == parent_id
    assert next_task["due_date"] == (date.today() + timedelta(days=7)).isoformat()

    db.delete_task(child_id)
    assert db.fetch_task_by_id(child_id) is None
