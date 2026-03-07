from __future__ import annotations

from datetime import date, timedelta

from db import Database, now_iso


def _insert(db: Database, description: str, **extra) -> int:
    payload = {
        "description": description,
        "sort_order": int(extra.pop("sort_order", 1)),
        "last_update": extra.pop("last_update", now_iso()),
    }
    payload.update(extra)
    return db.insert_task(payload)


def test_fetch_task_relationships_reports_dependencies_and_context(tmp_path):
    db = Database(str(tmp_path / "tasks.sqlite3"))
    today = date.today().isoformat()

    root_id = _insert(db, "Website launch", planned_bucket="today", sort_order=1)
    design_id = _insert(db, "Finalize design", parent_id=root_id, due_date=today, priority=1, sort_order=1, tags=["work"])
    content_id = _insert(
        db,
        "Collect final copy",
        parent_id=root_id,
        due_date=today,
        priority=2,
        sort_order=2,
        tags=["work"],
        waiting_for="Alex",
        last_update=(date.today() - timedelta(days=5)).isoformat() + " 09:00:00",
    )
    qa_id = _insert(db, "QA sign-off", due_date=today, priority=2, sort_order=3, tags=["work"])
    partner_id = _insert(
        db,
        "Partner approval",
        due_date=(date.today() + timedelta(days=1)).isoformat(),
        priority=3,
        sort_order=4,
        waiting_for="Alex",
    )

    db.set_task_dependencies(qa_id, [design_id])

    relationships = db.fetch_task_relationships(design_id, limit=10)

    assert relationships["task"]["id"] == design_id
    assert relationships["parent"]["id"] == root_id
    assert [row["id"] for row in relationships["siblings"]] == [content_id]
    assert [row["id"] for row in relationships["dependents"]] == [qa_id]
    assert {row["id"] for row in relationships["same_tags"]} == {content_id, qa_id}
    assert {row["id"] for row in relationships["same_waiting_for"]} == set()
    assert relationships["due_day_load"]["task_count"] >= 3

    waiting_relationships = db.fetch_task_relationships(content_id, limit=10)
    assert {row["id"] for row in waiting_relationships["same_waiting_for"]} == {partner_id}
