from __future__ import annotations

from datetime import date, timedelta

from db import Database, now_iso


def test_fetch_focus_data_surfaces_today_overdue_and_next_actions(tmp_path):
    db = Database(str(tmp_path / "focus.sqlite3"))
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    today_task = db.insert_task(
        {"description": "Today item", "due_date": today, "sort_order": 1, "last_update": now_iso(), "planned_bucket": "today"}
    )
    project_id = db.insert_task({"description": "Project", "sort_order": 2, "last_update": now_iso()})
    next_child_id = db.insert_task(
        {"description": "Next child", "parent_id": project_id, "sort_order": 1, "last_update": now_iso(), "due_date": tomorrow}
    )
    blocked_id = db.insert_task(
        {"description": "Blocked today", "sort_order": 3, "last_update": now_iso(), "due_date": today, "planned_bucket": "today"}
    )
    waiting_id = db.insert_task(
        {"description": "Waiting today", "sort_order": 4, "last_update": now_iso(), "due_date": today, "planned_bucket": "today"}
    )
    dependency_id = db.insert_task({"description": "Dependency", "sort_order": 5, "last_update": now_iso()})

    db.set_task_dependencies(blocked_id, [dependency_id])
    db.update_task_field(waiting_id, "waiting_for", "Alex")

    rows = db.fetch_focus_data(include_waiting=False, limit=20)
    ids = {int(row["id"]) for row in rows}
    sections = {int(row["id"]): str(row.get("focus_section") or "") for row in rows}

    assert today_task in ids
    assert next_child_id in ids
    assert blocked_id not in ids
    assert waiting_id not in ids
    assert sections[today_task] == "Today"
    assert sections[next_child_id] == "Next action"

    rows_with_waiting = db.fetch_focus_data(include_waiting=True, limit=20)
    ids_with_waiting = {int(row["id"]) for row in rows_with_waiting}
    sections_with_waiting = {int(row["id"]): str(row.get("focus_section") or "") for row in rows_with_waiting}

    assert blocked_id in ids_with_waiting
    assert waiting_id in ids_with_waiting
    assert sections_with_waiting[blocked_id] == "Waiting/Blocked"
    assert sections_with_waiting[waiting_id] == "Waiting/Blocked"
